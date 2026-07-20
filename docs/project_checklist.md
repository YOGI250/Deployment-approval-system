# AI-Powered Deployment Approval Assistant — Build Status

This originally listed pre-build planning tasks. Everything below has since
been built and deployed; this now tracks actual completion status as of
2026-07-21, plus what's genuinely still open.

## Group 1 — Azure DevOps side
- [x] Azure DevOps org/project + Git repo (lives in the separate pipeline repo)
- [x] Pipeline (build + test) configured
- [x] "AI Risk Analysis" pipeline stage calling `POST /predict` via inline curl (not a native "Invoke REST API" Environment Check — corrected in docs, functionally equivalent)
- [x] `POST /deployment-verification` wired up so the pipeline reports back what `GET /health` returned post-deploy
- [x] Confirm the pipeline actually branches on `risk_level`/`suggested_action` — **verified live for all three branches**: Low→`DeployProduction`/`production` (run `#20260720.7`), Medium→`DeployProductionManual`/`production-manual` with a real Azure DevOps Approval check requiring manual sign-off (run `#20260720.8`, audit row `id 99`), High→`RejectDeployment`/hard exit (rows `id 26`, `id 8`, `id 10`). Note: "Deploy Application" steps are intentional `echo` placeholders in every branch — this pipeline validates the risk gate, not a real app deployment, by design.

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
- [ ] Retrain → production isn't fully automated — see "Remaining open items" below

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
- [x] Dry run the full demo end to end, including the Azure DevOps gate actually pausing/resolving live — done 2026-07-21, all three branches (see Group 1)
- [x] Decide what to do with `data/audit_log.db` — deleted (untracked SQLite leftover, all rows already in Neon)

## Remaining open items (as of 2026-07-21)
- [ ] Teams/Slack — not implemented; email was the chosen channel (brief allows any of the three), worth flagging to evaluators explicitly rather than leaving ambiguous
- [ ] Real CI/CD from GitHub Actions to the Azure App Service — weekly model retrain commits to `main`, but shipping that to production is still a manual redeploy+restart; blocked on Azure CLI access (tenant security defaults blocked device-code login), explicitly deferred by the team for now
- [ ] `architecture-diagram.html` predates the Groq/LLM explanation step, `recovery_manager.py`, and email notifications — worth a refresh if evaluators will view it
