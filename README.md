# AI-Powered Deployment Approval Assistant

An AI-assisted system that scores the risk of a deployment (Low/Medium/High),
explains its reasoning, and recommends approve/delay/reject -- built to
integrate with Azure DevOps approval gates.

See `docs/requirement_traceability.md` for how every part of this maps back
to the original project brief.

## Project structure

```
deployment-approval-assistant/
├── app/                          All working code
│   ├── generate_deployment_history.py   Creates synthetic past-deployment data
│   ├── risk_scorer.py                   Calls Groq (LLM) to judge risk
│   ├── api.py                           FastAPI service (the main entry point)
│   ├── audit_log.py                     SQLite database logging
│   ├── email_notify.py                  Gmail notifications
│   └── dashboard.py                     Streamlit dashboard
├── data/                          Generated files (not hand-written, gitignored)
├── docs/                          Planning documents
├── requirements.txt                One-command dependency install
├── .env.example                    Template for required environment variables
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

- `POST /predict` -- send deployment details, get back a risk decision
- `GET /history` -- see every logged decision
- `POST /outcome` -- record what actually happened after a deployment, closing the feedback loop

## Production hardening (v2)

Beyond the core demo, this version adds real production-readiness features:

- **API authentication** -- `/predict`, `/outcome`, and `/history` require an
  `X-API-Key` header matching `API_KEY` in `.env`. Unset = unauthenticated
  with a loud warning logged (fine for local testing, never for a real deploy).
- **File criticality detection** -- if you send a `changed_files` list (real
  file paths), deployments touching payments/auth/config/security files are
  automatically treated as higher risk, regardless of file count.
- **Historical grounding (RAG)** -- the AI is shown the 3 most similar past
  deployments (same author, similar size) and their real outcomes before
  making its judgment, instead of reasoning in a vacuum every time.
- **Resilient AI calls** -- if Groq is slow or unreachable, the system retries
  with backoff, then fails SAFE (Medium risk, flagged for manual review)
  instead of crashing the whole deployment pipeline.
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
3. Update the Azure DevOps "Invoke REST API" check's **Headers** field to
   include the same key:
   ```json
   {
     "Content-Type": "application/json",
     "X-API-Key": "the-same-value-you-put-in-API_KEY"
   }
   ```
   Without this, the check will now get a 401 error, since the API is no
   longer open to unauthenticated callers.


# Deployment-approval-system
