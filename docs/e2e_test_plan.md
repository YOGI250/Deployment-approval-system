# End-to-End Test Plan — AI-Powered Deployment Approval Assistant

Grounded in `Yogeshwaran.pdf` (evaluator problem statement) and the actual
implementation in this repo (`app/*.py`) as of 2026-07-20. Each section maps
an evaluator requirement to a concrete, runnable test against the live API
(`https://deployment-approval-demo-dgcxg9habkenhwes.centralindia-01.azurewebsites.net`)
or against a local instance.

**How to use this in the other VS Code window (the pipeline repo):** open a
Claude Code session there, point it at this file (`docs/e2e_test_plan.md` in
this repo — same machine, so an absolute path works), and ask it to (a) run
the API-side cases directly with curl/httpx against the base URL above, and
(b) cross-check the "Azure DevOps pipeline" section against whatever
`azure-pipelines.yml` / approval-gate config lives in that repo, since this
repo has no pipeline YAML of its own.

Auth header for every `/predict`, `/outcome`, `/deployment-verification`
call: `X-API-Key: <API_KEY from .env>`.

---

## 1. Data collection & feature engineering

| Test | How | Expected |
|---|---|---|
| Commit complexity feature used | `POST /predict` with `files_changed: 50, lines_changed: 5000` vs `files_changed: 1, lines_changed: 5` | Higher-complexity payload should score higher risk / lower confidence, all else equal |
| Author success-rate lookup works | Submit several `/predict` + `/outcome` pairs for the same `author`, then a fresh `/predict` for that author | `reasoning` should reference author history once enough real outcomes exist (see `calculate_author_success_rate` in `risk_scorer.py`) |
| Pipeline stage success ratio honored | Vary `pipeline_stage_success_ratio` 0.2 → 1.0 with everything else fixed | Risk level should move inversely with the ratio |
| `changed_files` drives criticality | Include a path matching `_has_critical_files` (check `policy_engine.py` for the pattern list) vs. an unrelated file | Critical-file run should be more likely to trigger `rule_3`/`rule_4` |

## 2. AI-based risk assessment

| Test | How | Expected |
|---|---|---|
| Low risk case | High coverage (95%+), 0 tests failed, small diff, staging | `risk_level: "Low"`, `suggested_action` ≈ auto-approve wording |
| Medium risk case | Moderate coverage (60-75%), 1-2 tests failed | `risk_level: "Medium"` |
| High risk case | Low coverage (<50%), several tests failed, production | `risk_level: "High"` |
| Explainability present | Any `/predict` call | `reasoning` is non-empty free text specific to the input, not a generic placeholder |
| Model metadata correct | `GET /model-info` | `model`, `model_version` match what `/predict` responses report |
| Degraded mode | Temporarily break the model load path (or check `degraded` field under a forced `_get_model` failure, as `test_deployment_verification.py` does) | `degraded: true` and the API still returns a usable (fallback) response, not a 500 |

## 3. Approval workflow integration

| Test | How | Expected |
|---|---|---|
| Auto-approve low risk | Low-risk payload | `decide_action` → `"approve"` |
| Delay/extra-checks medium risk | Medium-risk payload | action reflects delay/additional-checks per `decision_engine.py` |
| Block high risk | High-risk payload | action reflects reject/block |
| Policy override — production min coverage | `environment: "production"`, `test_coverage_pct` below the configured minimum | `policy_override: true`, `"rule_1_production_min_coverage"` in `triggered_policies` |
| Policy override — global max failed tests | `tests_failed` above `global.maximum_failed_tests` (default 0) | `"rule_2_global_max_failed_tests"` triggered |
| Policy override — critical file coverage | Critical file + coverage under `critical_file_coverage_threshold` (60) | `"rule_3_global_critical_file_coverage"` triggered |
| Policy override — critical file + prod failure | production + critical file + `failed_at_stage` set | `"rule_4_production_critical_file_with_failures"` triggered |
| Friday evening escalation | production, `day_of_week: "Friday"`, an evening `hour` | `"rule_5_production_friday_evening_escalation"` triggered, risk escalated one level (`_escalate_one_level`) |
| **Azure DevOps gate itself** | *(in the other repo)* — trigger the actual pipeline run and watch the approval gate | **Verified live, all three branches.** Low → `DeployProduction`/`production`, auto-proceeds (confirmed run `#20260720.7`). Medium → `DeployProductionManual`/`production-manual`, pauses for a real Azure DevOps Approval check and only proceeds once approved (confirmed run `#20260720.8`, commit `387e644` in the pipeline repo — 20 files changed pushed it past the Low tier's file-count bar, `threshold_engine` escalated Low→Medium, decision `delay`, approved manually, deploy stage ran, `/deployment-verification` reported healthy, `/outcome` recorded `success` — audit row `id 99`, `deployment_id "65"`). High → `RejectDeployment`, hard `exit 1` (confirmed earlier, e.g. audit rows `id 26`, `id 8`, `id 10`). Note: the "Deploy Application" step in every branch is a simulated `echo` placeholder by design — this pipeline validates risk-gating/branching, not a real application deployment. |

## 4. Feedback loop & continuous learning

| Test | How | Expected |
|---|---|---|
| Outcome recording | `POST /outcome` with a `deployment_id` from a prior `/predict` | `200`, and the audit row's `actual_outcome`/`incident_severity` updated (check via `/history` or Neon directly) |
| Unknown deployment_id | `/outcome` with a `deployment_id` that was never predicted | Should not 500 — confirm graceful no-op or clear error |
| Threshold adjustment | Inspect `adjust_thresholds.py` — run it against a batch of recorded outcomes | Thresholds in `data/risk_thresholds.json` change in the expected direction (more failures → stricter) |
| Accuracy metrics | `accuracy_metrics.py::compute_approval_accuracy` against a mix of correct/incorrect predictions | Returns expected keys — **note:** `test_accuracy_metrics.py::test_result_has_exact_expected_keys` is currently FAILING (extra keys: `precision`, `true_positive`, `false_positive_rate`, `false_negative_rate`, `false_negative` beyond the expected `{correct, incorrect, total_verified, accuracy_pct}`). Worth deciding: update the test's expected key set, or trim the function's return shape, before calling this evaluation criterion "done." |

## 5. Reporting & dashboard

| Test | How | Expected |
|---|---|---|
| Dashboard loads | `streamlit run app/dashboard.py` | Renders without error against live `/history` |
| Risk predictions per run visible | Push a few varied `/predict` calls, refresh dashboard | New rows appear |
| Predicted vs actual accuracy view | After recording `/outcome`s | Dashboard's accuracy view reflects them |
| Trends by team/project | Vary `team` across requests | Dashboard breakdown groups correctly |

## 6. Notifications & communication

| Test | How | Expected |
|---|---|---|
| Decision notification | Any `/predict` call | `notify_decision` fires — check `GMAIL_ADDRESS` inbox |
| Outcome notification | `/outcome` call | `notify_outcome` fires |
| Verification failure notification | `POST /deployment-verification` with `http_status_code: 503` | `notify_verification_failure` fires |
| Recovery required notification | Unhealthy verification that `recovery_manager.evaluate_recovery` flags | `notify_recovery_required` fires, includes `rollback_recommended` |
| **Gap to flag with evaluators** | — | The brief asks for Teams **or** Email **or** Slack. Only Gmail/email is implemented (`email_notify.py`). If Teams/Slack is expected, that's a scope gap, not a bug — worth calling out explicitly rather than silently leaving it. |

## 7. Audit & compliance

| Test | How | Expected |
|---|---|---|
| Full round trip persisted | `/predict` → `/outcome` → `/deployment-verification` for one `deployment_id` | Single Neon row accumulates all fields: risk, decision, `actual_outcome`, `deployment_status`, `health_check`, `recovery_status` |
| Explainability retained in audit trail | `GET /history` | Every row includes `reasoning`, `policy_reason`, `triggered_policies` |
| Auth enforced | Call `/predict`, `/outcome`, `/deployment-verification` **without** `X-API-Key` | `401` on all three |
| Health/DB check | `GET /health` | `database: "connected"` against Neon (already verified working in production) |
| Data survives a bad request | Send a malformed payload (missing required field) | `422` from FastAPI validation, no partial/corrupt row written |

---

## Cross-cutting "all cases" checklist

- [ ] Boundary values: `test_coverage_pct` exactly at a threshold (e.g. exactly 60%, exactly 50%) — off-by-one on `<` vs `<=` in `policy_engine.py`
- [ ] `tests_failed: 0` vs `1` at the global max boundary
- [ ] Empty `changed_files: []`
- [ ] Very large `lines_changed` (stress the feature engineering, not just typical values)
- [ ] Concurrent `/predict` calls with the same `deployment_id` (race on the audit row)
- [ ] Duplicate `/outcome` calls for the same `deployment_id` (idempotency)
- [ ] `/deployment-verification` arriving before any matching `/predict` row exists
- [ ] Non-ASCII / unusually long strings in `author`, `team`, `deployment_id`
- [ ] Multiple pipelines/projects in flight simultaneously (the "scalability across multiple pipelines" evaluation criterion) — vary `team`/`environment` and confirm no cross-contamination in `/history`

## What to test in *this* repo vs. the *other* (pipeline) repo

| Belongs here (deployment-approval-assistant) | Belongs in the pipeline repo |
|---|---|
| Model accuracy, policy rules, audit persistence, dashboard, notifications | Actually calling `/predict` from an Azure DevOps task |
| API auth, `/health`, `/deployment-verification` | Branching the approval gate on the response (approve/wait/block) |
| — | Calling `/deployment-verification` ~20s post-deploy per the DEV-009 comment in `api.py` |
| — | Whatever mechanism blocks the release for High risk (manual approval task, gate check, etc.) |

That last row is the one that mattered most to verify — it's the actual
"integration with Azure DevOps approval gates" the evaluators are scoring,
and it lives entirely outside this repo. As of 2026-07-21 it's fully
verified: all three decision branches have run for real against the live
pipeline, including a genuine human approval gate on the delay path (not
just a script that logs the decision).
