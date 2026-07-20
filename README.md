# AI-Powered Deployment Approval Assistant

An AI-assisted system that scores the risk of a deployment (Low/Medium/High)
with a trained RandomForest classifier, explains its reasoning with an LLM,
applies deterministic organizational safety policies on top, and recommends
approve/delay/reject -- integrated with Azure DevOps approval gates via an
inline curl call to `/predict` in the pipeline's "AI Risk Analysis" stage,
branching into three conditional deploy stages (approve/delay/reject).

See `docs/requirement_traceability.md` for how every part of this maps back
to the original project brief, and `docs/PROJECT_REPORT.md` for the full
submission writeup.

## Project structure

```
deployment-approval-assistant/
├── app/                              All working code
│   ├── generate_deployment_history.py   Creates synthetic past-deployment data
│   ├── feature_engineering.py           Builds the feature vector fed to the model
│   ├── ml/
│   │   ├── train_model.py                   Trains the RandomForest classifier
│   │   ├── predictor.py                      Loads data/model.pkl, predicts risk_level + confidence
│   │   └── model_utils.py                    Model save/load, feature-vector helpers
│   ├── risk_scorer.py                   Orchestrates: features -> ML model -> policy_engine -> Groq (explanation only)
│   ├── policy_engine.py                 Deterministic organizational rules that can override the ML prediction
│   ├── decision_engine.py               Maps risk_level -> approve/delay/reject
│   ├── recovery_manager.py              Classifies post-deploy health failures, recommends rollback
│   ├── model_info.py                    Real, verifiable facts about the deployed model (for the dashboard)
│   ├── adjust_thresholds.py             Recalibrates data/risk_thresholds.json from real outcomes
│   ├── accuracy_metrics.py              Predicted-vs-actual accuracy computation
│   ├── api.py                           FastAPI service (the main entry point)
│   ├── database.py / models.py          SQLAlchemy engine + AuditLog ORM model (Neon Postgres)
│   ├── audit_log.py                     Audit trail read/write functions (Neon Postgres, was SQLite pre-migration)
│   ├── email_notify.py                  Gmail notifications
│   └── dashboard.py                     Streamlit dashboard
├── data/                              Generated files (not hand-written, gitignored)
├── docs/                              Planning + submission documents
├── tests/                             pytest suite
├── requirements.txt                    One-command dependency install
├── .env.example                        Template for required environment variables
└── .gitignore
```

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt --break-system-packages
   ```

2. Create your real `.env` file by copying the template, then fill in your
   actual values:
   ```
   cp .env.example .env
   ```
   Edit `.env` and replace the placeholder values with your real
   `GROQ_API_KEY`, `GMAIL_ADDRESS`, and `GMAIL_APP_PASSWORD`.

   This file is loaded automatically every time you run any script --
   no need to `export` anything manually, and no need to re-do this
   every time you open a new terminal. `.env` is already excluded from
   git via `.gitignore`, so your real keys never get committed.

## Running everything

Run each of these in order, in **separate terminals**, all with the env
variables set. All commands below assume you've moved into the `app/`
folder first (`cd app`) -- the scripts are written to import each other
directly, so they need to run from inside that folder.

1. Generate the synthetic dataset (run once):
   ```
   cd app
   python3 generate_deployment_history.py
   ```

2. Start the API (from inside `app/`):
   ```
   uvicorn api:app --reload --port 8001
   ```
   Test it at http://127.0.0.1:8001/docs

3. Start the dashboard (separate terminal, also from inside `app/`):
   ```
   streamlit run dashboard.py --server.port 8502
   ```

## What each endpoint does

- `POST /predict` -- send deployment details, get back a risk decision (ML risk level + confidence, policy overrides, LLM reasoning, suggested action)
- `GET /history` -- see every logged decision
- `POST /outcome` -- record what actually happened after a deployment, closing the feedback loop
- `POST /deployment-verification` -- pipeline reports the post-deploy `/health` result; persisted against the matching audit row and run through `recovery_manager` for a rollback recommendation
- `GET /health` -- liveness + DB connectivity check, also what the pipeline polls ~20s after deploy
- `GET /model-info` -- real facts about the currently loaded model (name, version, feature count, last-updated)
- `GET /` -- basic root health check (unauthenticated)

## Production hardening (v2)

Beyond the core demo, this version adds real production-readiness features:

- **API authentication** -- `/predict`, `/outcome`, `/history`, and
  `/deployment-verification` require an `X-API-Key` header matching `API_KEY`
  in `.env`. Unset = unauthenticated with a loud warning logged (fine for
  local testing, never for a real deploy).
- **File criticality detection** -- if you send a `changed_files` list (real
  file paths), deployments touching payments/auth/config/security files are
  automatically treated as higher risk, regardless of file count.
- **Historical grounding (RAG)** -- the AI is shown the 3 most similar past
  deployments (same author, similar size) and their real outcomes before
  making its judgment, instead of reasoning in a vacuum every time.
- **Resilient AI calls** -- the risk *level* comes from the trained RandomForest
  model, not Groq, so an LLM outage never changes a risk decision. If Groq is
  slow or unreachable, the system retries with backoff, then falls back to a
  generic reasoning string (`degraded: true` in the response) instead of
  crashing the whole deployment pipeline.
- **Prompt versioning** -- every audit log row records which prompt/logic
  version made that decision (`prompt_version` column) -- a real compliance
  requirement for explaining decisions after the fact.
- **Automated tests** -- see `tests/`, run with `pytest tests/ -v` from the
  project root. Covers file criticality, historical retrieval, prompt
  building, the fail-safe retry path, and API authentication.

### Running the tests

```
cd deployment-approval-assistant
pytest tests/ -v
```

### Updating your live Azure deployment for these changes

1. Add `API_KEY` (any long random string) to your App Service's Environment
   variables in the Azure Portal, same place as `GROQ_API_KEY` etc.
2. Redeploy the updated code (VS Code Azure extension -> Deploy to Web App)
3. Update the `API_KEY` variable in the pipeline repo's `risk-assistant-secrets`
   variable group (Azure DevOps -> Pipelines -> Library) to the same value --
   the `AI Risk Analysis` stage's curl call sends it as the `X-API-Key`
   header. Without this, the call will now get a 401 error, since the API is
   no longer open to unauthenticated callers.


# Deployment-approval-system
