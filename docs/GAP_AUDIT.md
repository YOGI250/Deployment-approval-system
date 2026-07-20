# Gap Audit — AI-Powered Deployment Approval Assistant

Line-by-line audit of the evaluator brief (`Yogeshwaran.pdf`) against the
actual code in this repo, verified by direct file reads on 2026-07-20 (not
inferred from earlier docs). Each row cites the exact file/line proving the
status. ✅ = fully implemented and verified. ⚠️ = partially implemented, or
implemented but unconfirmed in a part of the system outside this repo. ❌ =
not implemented.

---

## Problem Objective

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Analyzes code changes, test results, deployment history | ✅ | `app/api.py:65-84` (`DeploymentRequest`), `app/feature_engineering.py`, `get_combined_history()` |
| 2 | Predicts risk level: Low / Medium / High | ✅ | `app/ml/train_model.py:41-47`, served via `app/ml/predictor.py` |
| 3 | Recommends approve / delay / reject | ✅ | `app/decision_engine.py` — deterministic `Low→approve, Medium→delay, High→reject` |
| 4 | Integrates with Azure DevOps pipelines and approval gates | ⚠️ | API side real (`/predict`); gate mechanism itself (native Check vs. script step) needs confirming in the pipeline repo |
| 5 | Audit trails + explainable AI decisions | ✅ | `app/audit_log.py` full lifecycle logging; `reasoning` populated every call |

## Scope — 1. Data Collection & Feature Engineering

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Build success/failure rates | ✅ | `data/deployment_history.csv` `outcome` column; real outcomes via `/outcome` |
| 2 | Test coverage and test failure patterns | ✅ | `test_coverage_pct`, `tests_failed` in `build_features()` |
| 3 | Code commit metadata (lines changed, files modified, author) | ✅ | `files_changed`, `lines_changed`, `author` |
| 4 | Deployment environment and stage metrics | ✅ | `environment`, `pipeline_stage_success_ratio`, `failed_at_stage` |
| 5 | Feature: commit complexity | ✅ | `files_changed` + `lines_changed` |
| 6 | Feature: pipeline stage success ratio | ✅ | `app/feature_engineering.py:88` |
| 7 | Feature: recent changes by same author | ✅ | `calculate_author_success_rate()` |
| 8 | Feature: recent changes by same team | ❌ | `team` is captured as text/metadata (shown to Groq, used for dashboard filter) but **no `team_success_rate` feature is engineered or fed to the ML model** |

Minor: `app/feature_engineering.py`'s own module docstring still says *"not
wired into the live /predict flow yet"* — stale; confirmed live at
`app/risk_scorer.py:339`.

## Scope — 2. AI-Based Risk Assessment

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Train model to predict deployment failure likelihood | ✅ | RandomForest, `app/ml/train_model.py` |
| 2 | Assign risk categories: Low / Medium / High | ✅ | Confirmed above |
| 3 | Model explainability — reasoning behind decisions | ✅ | Groq `reasoning`, grounded in real thresholds (`app/risk_scorer.py:174-179`) |

## Scope — 3. Approval Workflow Integration

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Auto-approve low-risk | ✅ (API side) | `decision_engine.py` |
| 2 | Suggest additional checks / delay medium-risk | ✅ (API side) | `decision_engine.py` |
| 3 | Block high-risk until manual review | ✅ (API side) | `decision_engine.py` |
| 4 | Integrate with Azure DevOps approval gates so this actually branches pipeline behavior | ⚠️ | Same unconfirmed item as Problem Objective #4 |

## Scope — 4. Feedback Loop & Continuous Learning

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Collect post-deployment outcomes: success/failure | ✅ | `POST /outcome` → `update_outcome()`, `app/api.py:259-280` |
| 2 | Test coverage and production incidents | ✅ | `incident_severity` recorded per outcome |
| 3 | Retrain AI model periodically | ⚠️ | `train_model.py` works but nothing schedules it — manual only |
| 4 | Adjust risk thresholds dynamically based on pipeline performance | ⚠️ | `adjust_thresholds.py` real and already used once for real (tightened Low coverage bar 80%→85%), but its own comment (`app/adjust_thresholds.py:20`) says "run manually, or on a schedule" — no schedule exists |

## Scope — 5. Reporting & Dashboard

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Risk predictions per commit/pipeline run | ✅ | Dashboard "Latest Deployment" + full audit table, live from `/history` |
| 2 | Historical approval accuracy (predicted vs actual) | ✅ | Accuracy %, precision/recall, confusion matrix, daily trend (`app/dashboard.py:221-286`) |
| 3 | Trends/risk patterns by project or team | ✅ | Team multiselect filter + "Trends" section |

## Scope — 6. Notifications & Communication

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Notify via Teams, Email, or Slack | ⚠️ | Only Email (`smtplib`/Gmail). Brief says "or," so technically satisfied, but no Teams/Slack exists at all |
| 2 | Deployment approvals recommended/blocked | ✅ | `notify_decision()` |
| 3 | Risk insights and suggested mitigation steps | ✅ | Email body includes `reasoning` + `suggested_action` verbatim |
| 4 | Post-deployment outcomes for feedback | ✅ | `notify_outcome()` |

## Scope — 7. Audit & Compliance

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Log AI recommendations | ✅ | `reasoning`, `risk_level`, `confidence` per row |
| 2 | Log deployment decisions (approved/blocked/delayed) | ✅ | `decision`, `policy_override`, `triggered_policies` |
| 3 | Log execution outcomes | ✅ | `actual_outcome`, `deployment_status`, `health_check`, `recovery_status` |
| 4 | Decisions explainable and reviewable | ✅ | `reasoning` + `policy_reason` on every row, surfaced directly in dashboard |

## Expected Deliverables

| # | Deliverable | Status | Evidence |
|---|---|---|---|
| 1 | Architecture diagram | ⚠️ | `architecture-diagram.html` exists (511 lines) and is accurate for the core flow (Developer → Pipeline → FastAPI → Feature Engineering → RandomForest → Policy Engine → Decision Engine → Health Check → Verification → Audit DB) — but **missing** the Groq/LLM explanation step, `recovery_manager.py`, and the email notification layer |
| 2 | AI/ML model for deployment risk prediction | ✅ | RandomForest, confirmed live |
| 3 | Azure DevOps pipeline integration with approval gates | ⚠️ | Same unconfirmed item as above |
| 4 | Dashboard with risk analytics and post-deployment insights | ✅ | Confirmed |
| 5 | Notifications and communication workflow | ⚠️ | Email-only, content quality good |
| 6 | Documentation including audit trail and explainability | ✅ | `docs/PROJECT_REPORT.md`, `docs/requirement_traceability.md`, `docs/e2e_test_plan.md`, `docs/project_checklist.md` + live audit trail |

## Evaluation Criteria — self-assessment

| # | Criterion | Assessment |
|---|---|---|
| 1 | Accuracy of AI risk prediction | Measurable (`accuracy_metrics.py`, dashboard confusion matrix), but only as strong as real `/outcome` volume — currently thin, mostly synthetic history |
| 2 | Correct integration with Azure DevOps approval gates | **Weakest point overall** — this is a named deliverable *and* evaluation criterion, and it's the one thing not directly verified in this repo |
| 3 | Reduction in failed deployments/incidents | No before/after baseline measured yet — policy engine is the mechanism, but the *reduction* claim itself isn't quantified over time |
| 4 | Explainability of AI decisions | Strong — real reasoning text grounded in real threshold numbers, plus named policy rules when triggered |
| 5 | Quality of dashboards and notifications | Dashboard exceeds the ask (precision/recall/confusion matrix); notifications solid but single-channel |
| 6 | Practicality/scalability across multiple pipelines | Structurally supported (`team`/`environment` fields, Neon handles concurrency) but never demonstrated live with 2+ pipelines running concurrently |

---

## Consolidated priority gap list

Ranked by how much an evaluator is likely to weight them (ties to a named
deliverable or evaluation criterion first):

1. **Azure DevOps gate mechanism unconfirmed** — is it a native blocking Check, or just a script step logging the response? Verify directly in the pipeline repo. *(Named deliverable + evaluation criterion — highest priority)*
2. **"Reduction in failed deployments" not actually measured** — no before/after baseline exists. *(Named evaluation criterion)*
3. **No Teams/Slack notifications** — email only. *(Named deliverable, technically satisfied by "or" but worth flagging)*
4. **No automated model retraining schedule** — manual only.
5. **No automated threshold-adjustment schedule** — manual only, despite brief's "dynamically."
6. **Multi-pipeline scalability never demonstrated live** — structurally ready, not proven.
7. **Architecture diagram missing 3 real components** (Groq/LLM, recovery manager, email notifications).
8. **Team-level success-rate feature not engineered** — author-only.
9. Stale docstring in `feature_engineering.py` — cosmetic.

Items 1-3 are the ones most likely to cost points directly against named
evaluation criteria. Items 4-6 are real but lower-stakes since the brief's
wording ("or," "periodically") gives some latitude. Items 7-9 are polish.
