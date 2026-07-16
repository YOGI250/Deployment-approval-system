"""
risk_scorer.py

Purpose: orchestrates one deployment's risk decision end to end:

    deployment -> feature_engineering -> ml.predictor -> decision_engine
               -> Groq (explanation only) -> merged response

The ML model (Random Forest, via app/ml/predictor.py) is the sole
source of risk_level and confidence. decision_engine.py is the sole
source of the business decision (approve/delay/reject). Groq is called
only to generate human-readable reasoning and a suggested mitigation
step for a risk level it did not choose -- it never determines risk,
confidence, or decision, and its output is discarded/ignored for those
fields even if it tries to include them.

Before running: set your Groq API key as an environment variable:
    export GROQ_API_KEY="your-key-here"        (Mac/Linux)
    set GROQ_API_KEY=your-key-here              (Windows cmd)

Install the Groq library first:
    pip install groq --break-system-packages
"""

import os
import json
import csv
import time
import logging
import env_loader  # loads .env file automatically -- must come before reading env vars
from groq import Groq

from feature_engineering import build_features, calculate_author_success_rate
from ml.predictor import predict as ml_predict
from policy_engine import evaluate_policies
from decision_engine import decide_action

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("risk_scorer")

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Points to data/deployment_history.csv regardless of what directory this
# script is run from
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
HISTORY_CSV_PATH = os.path.join(DATA_DIR, "deployment_history.csv")
THRESHOLDS_PATH = os.path.join(DATA_DIR, "risk_thresholds.json")


def load_thresholds() -> dict:
    """
    Loads risk thresholds from an external config file instead of having
    them hardcoded in the prompt text. adjust_thresholds.py can rewrite
    this file based on real outcomes, and every subsequent call picks up
    the change immediately, no code deploy needed. These thresholds are
    no longer used to classify risk (the ML model does that) -- they're
    passed to Groq purely as reference context to help it explain a
    decision in terms a reviewer will recognize.
    """
    try:
        with open(THRESHOLDS_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("risk_thresholds.json not found, using built-in defaults")
        return {
            "low": {"max_files_changed": 20, "min_test_coverage_pct": 80, "max_tests_failed": 0, "min_author_success_rate": 0.85},
            "medium": {"max_files_changed": 50, "min_test_coverage_pct": 60, "max_tests_failed": 1, "min_author_success_rate": 0.70},
        }

# Using Llama 3.3 70B via Groq -- fast and strong enough for structured
# explanation-writing tasks like this.
MODEL = "llama-3.3-70b-versatile"

# Bump this whenever SYSTEM_PROMPT or the explanation logic changes
# meaningfully. Stored on every audit log row -- lets you answer "which
# logic version made this call" during a compliance review.
# v3.0: Groq switched from classifying risk to explaining an ML-predicted
# risk level -- the risk judgment itself is no longer Groq's job.
# v4.0: the risk level Groq explains may now reflect a deterministic
# enterprise policy override (see policy_engine.py) applied after the ML
# prediction -- Groq is told when that happened and why.
PROMPT_VERSION = "v4.0-policy-engine-integrated"

# Real teams don't treat every file as equally risky -- a change to a
# payment or auth file is inherently higher stakes than a change to docs
# or tests. This is a simple substring-based classifier; a more mature
# version would use a maintained CODEOWNERS-style mapping per repo.
CRITICAL_FILE_PATTERNS = [
    "payment", "billing", "auth", "login", "security", "credential",
    "secret", ".env", "config", "migration", "schema",
]


def classify_file_criticality(changed_files: list) -> dict:
    """
    Given a list of file paths changed in this deployment, flags whether
    any of them touch a critical area (payments, auth, config, etc).
    Returns {"has_critical_files": bool, "matched_files": [...]}.
    If no file list is available (older callers just send a count), this
    degrades gracefully rather than failing.
    """
    if not changed_files:
        return {"has_critical_files": False, "matched_files": []}

    matched = [
        f for f in changed_files
        if any(pattern in f.lower() for pattern in CRITICAL_FILE_PATTERNS)
    ]
    return {"has_critical_files": len(matched) > 0, "matched_files": matched}


def find_similar_past_deployments(deployment: dict, history_rows: list, top_n: int = 3) -> list:
    """
    Retrieval step (the 'RAG' piece): finds the most relevant past
    deployments to ground the LLM's explanation in real history instead
    of pure general judgment. Similarity here is intentionally simple --
    same author scores highest, then closeness in files_changed.
    A more mature version could weight by team, file overlap, or embeddings.
    """
    if not history_rows:
        return []

    author = deployment.get("author")
    try:
        files_changed = int(deployment.get("files_changed", 0))
    except (TypeError, ValueError):
        files_changed = 0

    def similarity_score(row):
        score = 0.0
        if row.get("author") == author:
            score += 10  # same author is the strongest signal we have
        try:
            row_files = int(row.get("files_changed", 0))
            score += max(0, 5 - abs(row_files - files_changed) / 10)
        except (TypeError, ValueError):
            pass
        return score

    ranked = sorted(history_rows, key=similarity_score, reverse=True)
    return ranked[:top_n]


def build_system_prompt(thresholds: dict) -> str:
    """
    Builds the system prompt dynamically from the thresholds config.
    Groq's job here is explanation, not classification: the risk_level
    and confidence are already decided by the ML model before this
    prompt is ever built. The thresholds are included only as reference
    context, so Groq's explanation talks in terms a reviewer already
    understands ("more files changed than the Low bar allows") instead
    of inventing its own criteria.
    """
    low = thresholds["low"]
    medium = thresholds["medium"]

    return f"""You are a senior DevOps release engineer explaining a deployment risk decision to a reviewer.

An ML model (Random Forest) has already classified this deployment's risk level and
computed a confidence score. In some cases, a mandatory enterprise safety policy has
then overridden that prediction -- if the deployment summary below includes an
"Enterprise Policy Override Applied" section, the risk level you are explaining is the
POLICY's final decision, not the model's raw statistical one; ground your explanation
in the stated policy reason rather than re-deriving it from the raw factors alone.
Either way, your job is NOT to classify or second-guess the risk level -- it is final.
Your job is to:
1. Explain in 1-2 short sentences WHY this deployment likely received that risk level,
   referencing the specific factors that most plausibly drove it (files/lines changed,
   test coverage, failed tests, author track record, critical files touched, timing,
   pipeline stage health, similar past deployments)
2. Suggest one concrete mitigation step the team could take if the risk is Medium or
   High (write "None needed" if Low)

Reference thresholds this team currently uses to calibrate what "Low", "Medium", and
"High" mean operationally (for context only -- do not re-derive the risk level from
these, just use them to explain the ML model's decision in familiar terms):
- LOW risk territory: files changed under {low['max_files_changed']}, test coverage {low['min_test_coverage_pct']}% or higher, {low['max_tests_failed']} failed tests, author success rate {low['min_author_success_rate']}+, no critical files touched
- MEDIUM risk territory: files changed {low['max_files_changed']}-{medium['max_files_changed']}, OR test coverage {medium['min_test_coverage_pct']}-{low['min_test_coverage_pct']}%, OR up to {medium['max_tests_failed']} failed test(s), OR author success rate {medium['min_author_success_rate']}-{low['min_author_success_rate']}, OR critical files touched with otherwise clean signals
- HIGH risk territory: files changed over {medium['max_files_changed']} AND test coverage under {medium['min_test_coverage_pct']}%, OR any failed tests combined with low coverage, OR critical files touched alongside other risk factors, OR a late Friday/weekend deploy combined with other risk factors

Respond ONLY with valid JSON in this exact format, nothing else, no markdown fences,
and no keys other than these two -- risk_level, confidence, and decision are not
yours to set:
{{"reasoning": "...", "suggested_action": "..."}}
"""


def build_deployment_description(
    deployment: dict,
    history_rows: list = None,
    prediction: dict = None,
    policy_override: dict = None,
) -> str:
    """
    Turns one row of deployment data into a clear description for the
    LLM, including file criticality and grounding from similar past
    deployments when available (the RAG piece). When `prediction` is
    provided (the FINAL risk decision -- ML output, or ML output after a
    policy override), it's appended so Groq knows what it's explaining --
    omitted entirely for callers that don't pass it, so this stays
    backward compatible with pre-DEV-002 callers/tests. When
    `policy_override` is also provided (only set when a policy actually
    changed the outcome), an additional block spells out the ML
    prediction vs. the enterprise policy override and why, so Groq
    explains the real reason instead of guessing from raw factors alone.
    """
    changed_files = deployment.get("changed_files", [])
    criticality = classify_file_criticality(changed_files)

    description = f"""Deployment details:
- Author: {deployment['author']} (recent success rate: {deployment.get('author_recent_success_rate', 'unknown')})
- Team: {deployment['team']}
- Files changed: {deployment['files_changed']}
- Lines changed: {deployment['lines_changed']}
- Test coverage: {deployment['test_coverage_pct']}%
- Tests failed: {deployment['tests_failed']}
- Environment: {deployment['environment']}
- Deploy time: {deployment['day_of_week']} at {deployment['hour']}:00
- Touches critical files (payments/auth/config/etc): {"YES -- " + ", ".join(criticality['matched_files']) if criticality['has_critical_files'] else "No"}
- Failed at pipeline stage: {deployment.get('failed_at_stage') or 'none -- build and test passed'}
- This pipeline's historical stage success ratio: {deployment.get('pipeline_stage_success_ratio', 'unknown')}
"""

    if history_rows:
        similar = find_similar_past_deployments(deployment, history_rows)
        if similar:
            description += "\nMost similar past deployments in this codebase, for context:\n"
            for row in similar:
                description += (
                    f"- Author {row.get('author')}, {row.get('files_changed')} files changed, "
                    f"outcome: {row.get('outcome')}"
                    f"{' (incident: ' + row.get('incident_severity') + ')' if row.get('incident_severity') and row.get('incident_severity') != 'none' else ''}\n"
                )

    if prediction:
        description += (
            f"\nML model's decision (already final -- explain this, do not re-classify):\n"
            f"- Risk level: {prediction['risk_level']}\n"
            f"- Confidence: {prediction['confidence']:.0%}\n"
            f"- Model: {prediction['model']} v{prediction['model_version']}\n"
        )

    if policy_override:
        description += (
            f"\nEnterprise Policy Override Applied:\n"
            f"ML Prediction:\n{policy_override['ml_prediction']}\n\n"
            f"Enterprise Policy Override:\n{policy_override['policy_override']}\n\n"
            f"Reason:\n{policy_override['reason']}\n"
        )

    return description


def _generate_explanation(system_prompt: str, description: str, max_retries: int) -> dict:
    """
    Calls Groq for reasoning + suggested_action only. Retries on
    transient failures (rate limits, network blips) with exponential
    backoff. If Groq is unreachable after all retries, or returns
    unparseable output, fails SAFE with a degraded placeholder --
    unlike before DEV-002, this can no longer fall back to a fabricated
    risk level, because risk_level isn't Groq's responsibility anymore;
    it's already been decided by the ML model before this function is
    ever called.
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": description},
                ],
                temperature=0.2,  # low temperature = more consistent, less "creative" answers
                timeout=15,
            )
            raw_text = response.choices[0].message.content.strip()

            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError:
                logger.warning("Groq returned non-JSON output, using degraded explanation: %s", raw_text[:200])
                return {
                    "reasoning": "AI explanation could not be parsed; the risk level and confidence above are still from the ML model and are unaffected.",
                    "suggested_action": "Manual review recommended -- AI explanation output was malformed",
                    "degraded": True,
                }

            # Groq's output is explanation-only -- pull just these two
            # keys, ignoring anything else it might have included
            # (including a risk_level it was told not to set).
            return {
                "reasoning": parsed.get("reasoning", "No reasoning provided."),
                "suggested_action": parsed.get("suggested_action", "No suggested action provided."),
                "degraded": False,
            }

        except Exception as e:
            last_error = e
            logger.warning("Groq call failed (attempt %d/%d): %s", attempt, max_retries, e)
            if attempt < max_retries:
                time.sleep(2 ** attempt)  # exponential backoff: 2s, 4s, 8s...

    logger.error("Groq unreachable after %d attempts, using degraded explanation: %s", max_retries, last_error)
    return {
        "reasoning": f"AI explanation service was unreachable after {max_retries} attempts ({last_error}). The risk level and confidence above are still from the ML model and are unaffected.",
        "suggested_action": "Manual review recommended -- AI explanation service was degraded at decision time",
        "degraded": True,
    }


def score_deployment(deployment: dict, history_rows: list = None, max_retries: int = 3) -> dict:
    """
    Orchestrates the full pipeline for one deployment:

        deployment -> feature_engineering -> ml.predictor -> policy_engine
                   -> decision_engine -> Groq (explanation only) -> response

    Returns:
        {
            "risk_level": "...", "confidence": 0.xx,        # from ML, possibly overridden by policy
            "decision": "...",                               # from decision_engine, on the FINAL risk_level
            "reasoning": "...", "suggested_action": "...",   # from Groq
            "model": "RandomForest", "model_version": "1.0",
            "prompt_version": "...", "degraded": bool,
            "policy_override": bool, "policy_reason": "..." | None,
            "triggered_policies": [...],
        }

    risk_level, confidence, decision, and the policy fields are unaffected
    by any Groq failure -- only reasoning/suggested_action degrade to a
    safe placeholder if the explanation call fails, since Groq no longer
    has any say in the risk judgment itself. confidence always reflects
    the ML model's own confidence in its original prediction, even when a
    policy override changes the risk_level that prediction gets attached to.
    """
    history_rows = history_rows or []

    features = build_features(deployment, history_rows=history_rows)
    ml_result = ml_predict(features)

    policy_result = evaluate_policies(deployment, ml_result)
    final_risk_level = policy_result["risk_level"]
    decision = decide_action(final_risk_level)  # decision engine sees the risk AFTER policy validation

    if policy_result["overridden"]:
        # Application log only -- never returned from the API. Kept here
        # (not in api.py) because this is the one place that has both the
        # original ML prediction and the final, policy-adjusted risk in
        # scope at the same time.
        logger.warning(
            "Policy override applied: deployment_id=%s original_ml_prediction=%s final_risk=%s triggered_policies=%s reason=%s",
            deployment.get("deployment_id"), ml_result["risk_level"], final_risk_level,
            policy_result["policy_triggered"], policy_result["override_reason"],
        )

    thresholds = load_thresholds()  # loaded fresh every call, so threshold edits take effect immediately
    system_prompt = build_system_prompt(thresholds)

    final_prediction = dict(ml_result)
    final_prediction["risk_level"] = final_risk_level

    policy_override_context = None
    if policy_result["overridden"]:
        policy_override_context = {
            "ml_prediction": ml_result["risk_level"],
            "policy_override": final_risk_level,
            "reason": policy_result["override_reason"],
        }

    description = build_deployment_description(
        deployment, history_rows, prediction=final_prediction, policy_override=policy_override_context
    )

    explanation = _generate_explanation(system_prompt, description, max_retries)

    return {
        "risk_level": final_risk_level,
        "confidence": ml_result["confidence"],
        "decision": decision,
        "reasoning": explanation["reasoning"],
        "suggested_action": explanation["suggested_action"],
        "model": ml_result["model"],
        "model_version": ml_result["model_version"],
        "prompt_version": PROMPT_VERSION,
        "degraded": explanation["degraded"],
        "policy_override": policy_result["overridden"],
        "policy_reason": policy_result["override_reason"],
        "triggered_policies": policy_result["policy_triggered"],
    }


def test_against_sample(num_samples=30):
    """
    Loads real rows from deployment_history.csv and checks whether the
    full pipeline's risk judgments (now ML-driven, not LLM-driven) make
    sense IN AGGREGATE.

    Important: we do NOT check "did every High prediction fail" -- risk is
    probabilistic, not a guarantee. A High-risk deployment succeeding
    sometimes is normal. The real question is whether deployments labeled
    High actually fail MORE OFTEN than ones labeled Low, across many
    examples. That's what this measures.
    """
    with open(HISTORY_CSV_PATH) as f:
        rows = list(csv.DictReader(f))

    sample = rows[:num_samples]
    buckets = {"Low": [], "Medium": [], "High": []}

    for row in sample:
        row["author_recent_success_rate"] = calculate_author_success_rate(row["author"], rows)
        result = score_deployment(row)

        predicted_risk = result["risk_level"]
        actual_failed = 1 if row["outcome"] == "fail" else 0

        if predicted_risk in buckets:
            buckets[predicted_risk].append(actual_failed)

        print(f"Deployment {row['deployment_id']}: predicted {predicted_risk} (confidence {result['confidence']:.0%}), actual {row['outcome']}")

    print("\n--- Aggregate check: does actual failure rate increase with predicted risk? ---")
    for level in ["Low", "Medium", "High"]:
        outcomes = buckets[level]
        if outcomes:
            fail_rate = sum(outcomes) / len(outcomes)
            print(f"{level}: {len(outcomes)} deployments, {fail_rate:.0%} actually failed")
        else:
            print(f"{level}: no deployments predicted at this level in this sample")

    print("\nGood sign: fail rate should climb as you go Low -> Medium -> High.")
    print("If it doesn't, the ML model likely needs retraining/tuning.")


if __name__ == "__main__":
    test_against_sample(num_samples=30)
