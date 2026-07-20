# AI-Powered Deployment Approval Assistant — Build Status

This originally listed pre-build planning tasks. Everything below has since
been built and deployed; this now tracks actual completion status as of
2026-07-20 (updated same day, evening), plus what's genuinely still open.

## Group 1 — Azure DevOps side
- [x] Azure DevOps org/project + Git repo (lives in the separate pipeline repo)
- [x] Pipeline (build + test) configured
- [x] Environment with an "Invoke REST API" Check calling `POST /predict`
- [x] `POST /deployment-verification` wired up so the pipeline reports back what `GET /health` returned post-deploy
- [ ] Confirm the pipeline actually branches on `risk_level`/`suggested_action` (auto-approve/wait/block), not just logs the response — verify per `docs/e2e_test_plan.md` section 3

## Group 2 — The AI brain
- [x] Deployment data schema defined (`DeploymentRequest` in `api.py`)
- [x] Trained RandomForest classifier for risk level (`app/ml/train_model.py`)
- [x] Groq LLM for plain-English reasoning + suggested action (classification-free, explanation only)
- [x] Deterministic policy engine layered on top (`policy_engine.py`) — organizational rules that can override the ML prediction
- [x] Degraded-mode fail-safe if Groq is unreachable (retries, then generic explanation, never a 500)

## Group 3 — The connector service
- [x] FastAPI service with `/predict`, `/outcome`, `/deployment-verification`, `/health`, `/history`, `/model-info`
- [x] API key authentication (`X-API-Key` header)
- [x] Deployed to Azure App Service (Linux), reachable at a permanent URL
- [x] Verified live end-to-end against production (predict → Neon → history)

## Group 4 — Record keeping
- [x] Neon (managed Postgres) audit database via SQLAlchemy — migrated from an earlier SQLite prototype
- [x] Streamlit dashboard reading live from `/history`
- [x] Model Information panel showing real, verifiable model facts (no fabricated metrics)
- [x] Charts: risk over time, approve/delay/reject counts, trends by team

## Group 5 — Notifications
- [x] Email on decision, outcome, verification failure, and recovery-required (4 distinct notification points)
- [x] Real email delivery tested against a live Gmail inbox
- [ ] Teams/Slack — not implemented; email was the channel chosen (brief allows any of the three)

## Feedback loop & continuous learning
- [x] Real post-deployment outcomes logged via `/outcome` (not simulated)
- [x] `adjust_thresholds.py` — recalibrates `data/risk_thresholds.json` from real recorded outcomes
- [x] `accuracy_metrics.py` — predicted-vs-actual accuracy computation
- [x] `threshold_engine.py` — the recalibrated `risk_thresholds.json` now actually escalates decisions, not just Groq's explanation text
- [x] Scheduled/automatic model retraining — `.github/workflows/scheduled-maintenance.yml`, runs weekly, verified live (real run retrained the model and committed it back to `main`)
- [ ] **New gap found running the above**: the retrain job commits an updated `model.pkl` to `main`, but deploy to Azure App Service is still a manual step (VS Code extension) with no CI/CD watching this repo — so a Monday retrain doesn't reach production until someone manually redeploys *and restarts* the app. Confirmed via a live incident today: two manual redeploys silently had zero effect until an explicit App Service restart. Worth real CI/CD (GitHub Actions → Azure) once Azure CLI access is sorted (currently blocked by tenant security defaults on the account tested).

## Recovery & post-deploy verification (beyond original scope)
- [x] `recovery_manager.py` — classifies post-deploy health failures and recommends rollback, without attempting to touch Azure itself
- [x] Persisted to the audit row alongside the original decision (`recovery_status`, `rollback_recommended`, `recovery_reason`)

## Testing & documentation
- [x] pytest suite covering audit log, deployment verification, recovery manager, API auth, threshold engine, multi-pipeline concurrency (160 tests, all passing)
- [x] `test_accuracy_metrics.py::test_result_has_exact_expected_keys` — fixed, test updated to match `compute_approval_accuracy`'s real (precision/recall/confusion-matrix) return shape
- [x] `docs/requirement_traceability.md` — updated to reflect the shipped build, not the original plan
- [x] `docs/e2e_test_plan.md` — end-to-end test matrix mapped to evaluator criteria
- [x] `docs/PROJECT_REPORT.md` — standalone submission writeup

## Final polish
- [ ] Dry run the full demo end to end, including the Azure DevOps gate actually pausing/resolving live
- [ ] Decide what to do with `data/audit_log.db` (old SQLite file — all rows already copied to Neon, now redundant)
