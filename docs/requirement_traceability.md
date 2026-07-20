# Requirement-to-Implementation Traceability
## AI-Powered Deployment Approval Assistant

This document maps every line of the project brief (`Yogeshwaran.pdf`) to
what was actually built, with which tech, and why -- reflecting the shipped
system as of 2026-07-20, not the original build plan (see git history / the
original version of this file for how the plan evolved).

---

## 1. Problem Objective -- line by line

### "Analyzes code changes, test results, and deployment history"
- **What was built**: `feature_engineering.py` turns a deployment request
  (files changed, lines changed, test coverage, tests failed, author, team,
  environment, timing, changed file paths) into a feature vector, combined
  with historical context pulled from `data/deployment_history.csv`
  (synthetic) merged with real outcomes already recorded in the audit log.
- **Tech**: Python, `feature_engineering.py`, `risk_scorer.get_combined_history()`
- **Why this way**: Real audit history takes over from synthetic data
  automatically as real `/outcome` calls accumulate -- no manual cutover
  needed.

### "Predicts the risk level of a deployment (Low, Medium, High)"
- **What was built**: A trained **scikit-learn RandomForest classifier**
  (`app/ml/train_model.py` trains it, `app/ml/predictor.py` loads
  `data/model.pkl` and predicts). This is a real trained model, not an LLM
  guess -- the classification decision is deterministic given the same
  feature vector.
- **Tech**: scikit-learn RandomForestClassifier, `app/ml/`
- **Why this way over the original plan's "ask an LLM to classify"**: a
  trained classifier is reproducible, fast, cheap, and doesn't depend on an
  external API being up just to get a risk label. It also frees the LLM to
  do the one thing it's actually good at: writing readable explanations.

### "Recommends whether to approve, delay, or reject the deployment"
- **What was built**: `decision_engine.py` -- a single dict lookup,
  `{"Low": "approve", "Medium": "delay", "High": "reject"}`, with an
  unrecognized risk level failing safe to `"delay"`.
- **Tech**: Plain Python, `decision_engine.decide_action()`
- **Why this way**: Deterministic and auditable -- the mapping from ML
  output to business action is one line of code you can point to, not
  buried in LLM phrasing.

### "Integrates with Azure DevOps pipelines and approval gates"
- **What was built**: An Azure DevOps Environment Check of type "Invoke
  REST API", configured with an `X-API-Key` header, calling `POST /predict`
  as a release gate. (This piece lives in the pipeline's own repo, not this
  one -- see `docs/e2e_test_plan.md` for how the two are tested together.)
  `POST /deployment-verification` closes the loop after deploy by recording
  what the pipeline observed when it polled `GET /health`.
- **Tech**: Azure DevOps native "Invoke REST API" check
- **Why this way**: The documented, built-in Azure DevOps mechanism for
  exactly this use case -- no custom Azure Function/Logic App needed.

### "Provides audit trails and explainable AI decisions for compliance"
- **What was built**: Every decision -- input features, ML risk level +
  confidence, policy overrides + reasons, LLM-written explanation,
  suggested action, final business decision, and (once known) real
  outcome, deployment verification result, and recovery recommendation --
  is written as one row per `deployment_id` to a Postgres table, updated
  in place as later stages (`/outcome`, `/deployment-verification`) report
  back.
- **Tech**: Neon (managed Postgres) + SQLAlchemy ORM (`app/database.py`,
  `app/models.py`, `app/audit_log.py`). Originally SQLite during early
  development; migrated to Neon for a real persistent, multi-instance-safe
  store (Azure App Service's local disk isn't durable across
  redeploys/restarts).
- **Why this way**: Same functional guarantee as SQLite (persistent,
  queryable rows) but durable and reachable from the deployed App Service
  regardless of which instance/redeploy is currently running.

---

## 2. Scope of the Problem -- section by section

### 2.1 Data Collection & Feature Engineering
- **Build success/failure rates, test coverage/failure patterns, commit
  metadata, deployment/stage metrics** → fields on `DeploymentRequest` in
  `api.py`: `files_changed`, `lines_changed`, `test_coverage_pct`,
  `tests_failed`, `changed_files`, `failed_at_stage`,
  `pipeline_stage_success_ratio`, `environment`, `day_of_week`, `hour`.
- **Commit complexity, pipeline stage success ratio, recent changes by
  author/team** → `feature_engineering.py` (`has_critical_files`,
  `is_risky_timing`, `calculate_author_success_rate`) plus
  `pipeline_stage_success_ratio` passed straight through as a feature.
- **Tech**: Python, `feature_engineering.py`, synthetic history generator
  (`generate_deployment_history.py`)
- **Status**: Implemented and wired into both the ML feature vector and the
  policy engine (critical-file detection, Friday-evening escalation).

### 2.2 AI-Based Risk Assessment
- **Predict likelihood of failure, assign risk categories** → RandomForest
  classifier (`app/ml/predictor.py`), returns `risk_level` +
  `confidence` (max class probability).
- **Explainability -- reasoning behind recommendations** → `risk_scorer.py`
  calls Groq (Llama 3.3 70B) with the *already-decided* risk level, feature
  context, and any policy override, and asks it only to explain in plain
  English and suggest a next action. Groq never overrides the risk level.
- **Tech**: scikit-learn (classification) + Groq API (explanation only),
  `PROMPT_VERSION`-tracked prompts for auditability
- **Status**: Implemented, including a fail-safe path -- if Groq is
  unreachable after retries, the response still returns the real ML risk
  level with a generic degraded explanation (`degraded: true`), never a 500.

### 2.3 Approval Workflow Integration
- **Auto-approve low, suggest checks/delay medium, block high until manual
  review** → `decision_engine.decide_action()` plus deterministic
  **policy overrides** in `policy_engine.py` (`data/deployment_policy.json`)
  that can escalate the ML's risk level regardless of what the model said:
  production minimum coverage, global max failed tests, critical-file
  coverage threshold, critical file + production failure, and Friday
  evening escalation.
- **Tech**: Azure DevOps "Invoke REST API" check + `policy_engine.py` +
  `decision_engine.py`
- **Status**: Implemented. This is a meaningful upgrade over the original
  plan -- organizational safety rules are enforced deterministically and
  can't be talked around by a model's statistical judgment.

### 2.4 Feedback Loop & Continuous Learning
- **Collect post-deployment outcomes** → `POST /outcome`
  (`actual_outcome`, `incident_severity`), persisted against the original
  audit row.
- **Retrain periodically** → `app/ml/train_model.py` retrains the
  RandomForest from `data/deployment_history.csv`; not yet scheduled
  automatically (would need a cron/pipeline trigger -- documented as the
  natural next step, not faked as already running).
- **Adjust risk thresholds dynamically** → `adjust_thresholds.py` reads
  real outcomes from the audit log and rewrites `data/risk_thresholds.json`
  with a logged reason (see `last_adjusted_reason` in that file for a real
  example: tightened the Low-risk coverage bar after a 25% real failure
  rate was observed).
- **Tech**: Neon Postgres audit table (`actual_outcome`,
  `incident_severity` columns), `adjust_thresholds.py`,
  `accuracy_metrics.py`
- **Status**: The data plumbing and threshold-adjustment mechanism are real
  and runnable, not simulated. Full scheduled retraining is the one piece
  still manual (see Known Gaps in `docs/PROJECT_REPORT.md`).

### 2.5 Reporting & Dashboard
- **Risk predictions per commit/run, historical approval accuracy
  (predicted vs actual), trends by project/team** → `dashboard.py`
  (Streamlit) reads live from `GET /history`.
- **Model Information panel** → `model_info.py` surfaces only real,
  verifiable facts about the deployed model (name, version, feature count,
  file mtime) -- explicitly avoids fabricating training-set size or
  offline accuracy figures that aren't actually persisted anywhere.
- **Tech**: Streamlit + pandas, HTTP calls to the live API (not a direct DB
  connection -- the dashboard has no idea the database changed from SQLite
  to Neon underneath it)
- **Status**: Implemented.

### 2.6 Notifications & Communication
- **Notify stakeholders -- approvals recommended/blocked, risk insights,
  post-deployment outcomes** → `email_notify.py` sends four distinct
  emails: `notify_decision` (every `/predict`), `notify_outcome` (every
  `/outcome`), `notify_verification_failure` (unhealthy post-deploy
  check), `notify_recovery_required` (when `recovery_manager` flags a
  rollback).
- **Suggested mitigation steps** → included in the decision email body via
  the LLM's `suggested_action` field.
- **Tech**: Python `smtplib` via Gmail (App Password), four templates
- **Status**: Implemented for email. **Not implemented**: Teams or Slack --
  the brief lists these as alternatives to email ("via Teams, Email, or
  Slack"), and email was the channel chosen; worth flagging explicitly to
  evaluators rather than leaving ambiguous.

### 2.7 Audit & Compliance
- **Logs of AI recommendations, deployment decisions, execution outcomes;
  explainable and reviewable** → one Neon Postgres row per
  `deployment_id`, readable via `GET /history` or the dashboard, updated in
  place across the deployment lifecycle (`/predict` → `/outcome` →
  `/deployment-verification`).
- **Tech**: Neon Postgres (single source of truth for both dashboard and
  audit trail)
- **Status**: Implemented, including the post-deploy verification and
  recovery-recommendation stages (`recovery_manager.py`) that go beyond
  what the original brief explicitly asked for.

---

## 3. Expected Deliverables -- mapped directly

| Deliverable (from brief) | What was delivered |
|---|---|
| Architecture diagram | `architecture-diagram.html` |
| AI/ML model for risk prediction | Trained RandomForest classifier (`app/ml/`) + Groq for explanation only |
| Azure DevOps pipeline integration with approval gates | "Invoke REST API" check calling `/predict`, plus `/deployment-verification` closing the post-deploy loop |
| Dashboard with risk analytics and post-deployment insights | Streamlit dashboard (`app/dashboard.py`) reading from `/history` |
| Notifications and communication workflow | Four-stage email notification flow (`email_notify.py`) |
| Documentation including audit trail and explainability | This document + `docs/PROJECT_REPORT.md` + the Neon audit log + per-decision reasoning strings |

---

## 4. Evaluation Criteria -- how each is satisfied

| Criterion | How the build satisfies it |
|---|---|
| Accuracy of AI risk prediction | `accuracy_metrics.py` computes predicted-vs-actual accuracy from real recorded outcomes; `adjust_thresholds.py` demonstrates the system actually reacting to that accuracy over time |
| Correct integration with Azure DevOps approval gates | Live "Invoke REST API" check pausing/resolving based on `/predict`'s response; verify end-to-end per `docs/e2e_test_plan.md` |
| Reduction in failed deployments or incidents | Policy engine's deterministic overrides (e.g. blocking production deploys under the coverage floor) are the concrete mechanism; `incident_severity` on `/outcome` lets this be measured over time |
| Explainability of AI decisions | Every decision has a stored, human-readable Groq-written reasoning string plus, when applicable, an explicit `policy_reason` naming which organizational rule fired |
| Quality of dashboards and notifications | Live Streamlit dashboard + real email delivery at each of the four notification points |
| Practicality and scalability | Neon Postgres (not file-based SQLite) supports concurrent App Service instances; `team`/`environment` fields already support multi-pipeline breakdown without code changes |

---

## 5. Full tech stack summary

| Layer | Tech used | Notes |
|---|---|---|
| CI/CD platform | Azure DevOps | Mandated by the brief |
| API service | Python + FastAPI | `app/api.py` |
| Risk classification | scikit-learn RandomForest, trained offline | `app/ml/` |
| Explanation / reasoning | Groq (Llama 3.3 70B) | Explanation only, never classification |
| Organizational policy | Deterministic rule engine | `policy_engine.py` + `data/deployment_policy.json` |
| Hosting | Azure App Service (Linux) | Deployed via VS Code Azure extension |
| Database | Neon (managed Postgres) via SQLAlchemy | Migrated from SQLite; see `MIGRATION_NEON.md` |
| Dashboard | Streamlit | `app/dashboard.py` |
| Notifications | Python `smtplib` (Gmail) | Teams/Slack not implemented |
| Tests | pytest | `tests/` |

---

## 6. What changed from the original plan

The earlier version of this document (written before the build started)
proposed letting Groq classify risk directly and store everything in
SQLite. Both changed during implementation:

- **Groq → RandomForest for classification.** A trained model gives
  deterministic, reproducible risk labels and removes risk classification's
  dependency on an external API's uptime. Groq was kept, but narrowed to
  explanation-only -- still satisfying the brief's explainability
  requirement, just via a more reliable division of labor.
- **SQLite → Neon Postgres.** Needed once the system moved from local
  development to a real Azure App Service deployment, where local disk
  isn't a durable place to keep the only copy of the audit trail.

Both changes were upgrades over the original plan, not compromises --
worth stating plainly if a reviewer asks why the build doesn't match the
first draft of this document.
