# AI-Powered Deployment Approval Assistant — Project Report

**Author**: Yogeshwaran
**Date**: 2026-07-20
**Live API**: `https://deployment-approval-demo-dgcxg9habkenhwes.centralindia-01.azurewebsites.net`

---

## 1. Summary

This project builds an AI-assisted approval gate for Azure DevOps release
pipelines. On every deployment, it scores risk (Low / Medium / High) using
a trained machine-learning classifier, applies deterministic organizational
safety rules on top of that score, explains the decision in plain English
via an LLM, and records the full decision — plus what actually happened
afterward — to a durable audit trail. The result is used as an Azure
DevOps release-gate check: low-risk deployments proceed automatically,
medium-risk ones are flagged for a closer look, and high-risk ones are
blocked pending manual review.

Beyond the brief's explicit scope, the system also verifies deployments
after the fact (polling `/health` post-deploy) and classifies whether a
failed deployment needs human recovery attention — closing the loop from
"predicted risk" all the way to "did it actually work."

## 2. Architecture

See `architecture-diagram.html` for the visual version. In short:

```
Azure DevOps Pipeline
      │  (AI Risk Analysis stage: inline curl to /predict)
      ▼
POST /predict  ──▶  feature_engineering.py
                          │
                          ▼
                RandomForest classifier  ──▶  risk_level, confidence
                          │
                          ▼
                  policy_engine.py  ──▶  deterministic overrides
                          │            (production coverage floor,
                          │             max failed tests, critical
                          │             files, Friday escalation)
                          ▼
                  decision_engine.py  ──▶  approve / delay / reject
                          │
                          ▼
                    Groq (Llama 3.3 70B)  ──▶  plain-English reasoning +
                          │                     suggested action
                          ▼
              ┌───────────┴───────────┐
              ▼                       ▼
     Neon Postgres audit row    email_notify.py
     (app/database.py,          (decision notification)
      app/models.py,
      app/audit_log.py)

Later, asynchronously:
  POST /outcome                 → updates the row, sends outcome email
  GET  /health (pipeline polls) → POST /deployment-verification
                                       → recovery_manager.py
                                       → updates the row, sends recovery
                                         email if rollback is recommended

Streamlit dashboard (app/dashboard.py) reads all of this live from
GET /history — no direct database access, so it stays correct regardless
of what's underneath the API.
```

## 3. What was implemented, by brief section

### 3.1 Data Collection & Feature Engineering
Every `/predict` request carries commit metadata (files/lines changed,
author, team), test results (coverage %, tests failed), environment,
timing (day of week, hour), and optionally real file paths for criticality
detection. `feature_engineering.py` turns these into the feature vector the
model consumes, including derived signals like the author's recent success
rate (computed from real audit history once it exists, synthetic data
before that).

### 3.2 AI-Based Risk Assessment
A **RandomForest classifier**, trained offline (`app/ml/train_model.py`)
on the engineered features, predicts `risk_level` and a confidence score.
This is the actual statistical model — not an LLM guess — so the same
inputs always produce the same risk label. Groq (Llama 3.3 70B) is called
*after* the risk level is already decided, purely to write a human-readable
explanation and a suggested next action; it never has the power to change
the risk classification.

### 3.3 Approval Workflow Integration
`decision_engine.py` maps risk level to action (Low→approve,
Medium→delay, High→reject). Layered on top, `policy_engine.py` enforces
organizational rules that can escalate risk regardless of what the model
said — e.g. production deployments below a minimum coverage threshold, any
deployment with more than the allowed number of failed tests, or a
production Friday-evening deploy. These rules live in
`data/deployment_policy.json`, editable without touching code. The Azure
DevOps side calls this from an inline curl script in the pipeline's "AI Risk
Analysis" stage, which then branches into three mutually-exclusive
conditional deploy stages keyed on the returned decision -- `DeployProduction`
(approve, environment `production`), `DeployProductionManual` (delay,
environment `production-manual`, gated by a real Azure DevOps Approval check),
and `RejectDeployment` (reject, hard `exit 1`). All three branches have been
exercised live end-to-end in the pipeline repo, including a real human
approval on the delay path (confirmed 2026-07-20/21 -- see `docs/e2e_test_plan.md`
section 3). Deploy stages themselves are simulated (`echo` placeholders) --
this pipeline validates the risk-gating logic, not a real target application
deployment, by design.

### 3.4 Feedback Loop & Continuous Learning
`POST /outcome` records what actually happened (success/fail,
incident severity) against the original prediction. `adjust_thresholds.py`
uses that real data to recalibrate `data/risk_thresholds.json` — this has
already run once for real: after observing a 25% real failure rate on
predictions labeled Low risk, it tightened the Low-risk coverage bar from
80% to 85%. `accuracy_metrics.py` computes predicted-vs-actual accuracy
from the same data. `threshold_engine.py` makes the recalibrated thresholds
actually escalate a deployment's risk level, not just inform Groq's
explanation text. Scheduled retraining is automated via
`.github/workflows/scheduled-maintenance.yml` (weekly GitHub Actions run,
verified live — a real run retrained the model and committed the update back
to `main`); see `docs/SCHEDULED_MAINTENANCE.md` for the one known gap this
doesn't close (shipping that retrain to the live Azure App Service is still
a manual redeploy+restart, not automated).

### 3.5 Reporting & Dashboard
A Streamlit dashboard reads live from `GET /history`: risk predictions per
run, approve/delay/reject counts, and breakdowns by team. A separate
"Model Information" panel (`model_info.py`) shows only real, verifiable
facts about the currently deployed model (name, version, feature count,
last-updated timestamp) — deliberately avoids fabricating a training-set
size or offline accuracy figure that isn't actually persisted anywhere.

### 3.6 Notifications & Communication
Four distinct emails, sent via Gmail (`email_notify.py`):
decision-made, outcome-recorded, verification-failed, and
recovery-required. Each includes the relevant reasoning/next-step context,
not just a status flag.

### 3.7 Audit & Compliance
Every deployment gets one row in a Neon (managed Postgres) table, updated
in place as later stages report back — so a single `deployment_id` shows
the full lifecycle: ML prediction, policy overrides, LLM reasoning,
business decision, real outcome, post-deploy health verification, and
recovery recommendation. This was originally SQLite during local
development; migrated to Neon once the system moved to Azure App Service,
where local disk isn't durable across restarts/redeploys. Full migration
details in `MIGRATION_NEON.md`.

## 4. Deliverables

| Deliverable | Status | Where |
|---|---|---|
| Architecture diagram | Done | `architecture-diagram.html` |
| AI/ML model for risk prediction | Done | `app/ml/` (RandomForest) + Groq (explanation) |
| Azure DevOps pipeline integration with approval gates | Done | Inline curl call to `/predict` and `/deployment-verification` in the pipeline repo, branching into 3 conditional deploy stages verified live (approve/delay/reject) |
| Dashboard with risk analytics and post-deployment insights | Done | `app/dashboard.py` |
| Notifications and communication workflow | Done (email) | `app/email_notify.py` |
| Documentation including audit trail and explainability | Done | This document + `docs/requirement_traceability.md` + Neon audit log |

## 5. Evaluation criteria — self-assessment

| Criterion | Assessment |
|---|---|
| Accuracy of AI risk prediction | Measurable via `accuracy_metrics.py` against real recorded outcomes; the system has already demonstrably reacted to a measured accuracy gap (the Low-risk threshold tightening above) |
| Correct integration with Azure DevOps approval gates | Verified live end-to-end for all three branches (approve/delay/reject), including a real human approval on the delay path — see `docs/e2e_test_plan.md` section 3 |
| Reduction in failed deployments or incidents | The policy engine is the concrete mechanism (e.g., blocking under-tested production deploys before they ship); measurable over time via `incident_severity` on `/outcome` |
| Explainability of AI decisions | Every decision stores a written reasoning string plus, when applicable, the specific named policy rule that fired |
| Quality of dashboards and notifications | Live dashboard, real email delivery confirmed against a real inbox |
| Practicality and scalability across multiple pipelines | Neon Postgres supports concurrent App Service instances (unlike file-based SQLite); `team`/`environment` fields already support per-pipeline breakdown with no code changes |

## 6. Known gaps and open items

Being direct about what isn't finished, rather than glossing over it:

- **Teams/Slack notifications** — not implemented; only email. The brief
  names email as an acceptable channel on its own, but if Teams/Slack was
  expected, this is a real gap.
- **Retrain reaching production isn't automated** — the weekly GitHub
  Actions job retrains the model and commits it to `main`, but shipping
  that to the live Azure App Service is still a manual redeploy, which
  separately needs an explicit App Service restart to actually take effect
  (confirmed via a live incident on 2026-07-20). Real CI/CD (GitHub Actions
  → Azure) would close this; currently blocked on Azure CLI access (tenant
  security defaults blocked a device-code login) — see
  `docs/SCHEDULED_MAINTENANCE.md`.
- **The demo pipeline doesn't deploy a real application** — its "Deploy
  Application" steps are intentional `echo` placeholders. The pipeline's
  actual, verified scope is the AI risk-gate and its three-way branch
  (approve/delay/reject), not shipping a real target app. This is a
  deliberate scope choice, not an oversight.
- **Architecture diagram is out of date** — `architecture-diagram.html`
  (kept outside this repo) is accurate for the core predict flow but
  predates the Groq/LLM explanation step, `recovery_manager.py`, and the
  email notification layer being added.

## 7. Tech stack

| Layer | Technology |
|---|---|
| CI/CD platform | Azure DevOps |
| API service | Python, FastAPI |
| Risk classification | scikit-learn RandomForest (trained offline) |
| Explanation / reasoning | Groq (Llama 3.3 70B) |
| Organizational policy | Deterministic rule engine (JSON-configured) |
| Hosting | Azure App Service (Linux) |
| Database | Neon (managed Postgres) via SQLAlchemy |
| Dashboard | Streamlit |
| Notifications | Python `smtplib` via Gmail |
| Tests | pytest |

## 8. Further reading

- `docs/requirement_traceability.md` — line-by-line mapping from the
  original brief to the implementation, including what changed from the
  initial plan and why.
- `docs/e2e_test_plan.md` — the end-to-end test matrix used to validate
  this system, including the boundary cases and the parts that require
  the separate pipeline repo to fully verify.
- `docs/project_checklist.md` — current build-status checklist.
- `MIGRATION_NEON.md` — details of the SQLite-to-Neon database migration.
