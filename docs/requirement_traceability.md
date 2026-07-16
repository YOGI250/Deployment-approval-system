# Requirement-to-Implementation Traceability
## AI-Powered Deployment Approval Assistant

This document maps every line of the project brief to exactly what you're building, how, with which tech, and why — so nothing in your build is unexplained if your POC asks "why did you use this."

---

## 1. Problem Objective — line by line

### "Analyzes code changes, test results, and deployment history"
- **What you build**: A feature-extraction step in your API that pulls commit metadata (files changed, lines added/removed, author) from Azure DevOps's REST API, plus a simulated historical dataset standing in for "deployment history"
- **Tech**: Azure DevOps REST API (Git/Commits endpoint) + a Python script generating realistic synthetic history
- **Alternative considered**: Wait for real production history — rejected, not available in a 1-week window
- **Why this way**: Structure is real (pulled from an actual Azure DevOps repo), volume is simulated and clearly labeled as such

### "Predicts the risk level of a deployment (Low, Medium, High)"
- **What you build**: A call to an LLM (Groq) with the deployment's details, asked to classify into exactly one of three categories
- **Tech**: Groq API (LLM-based reasoning, POC-approved)
- **Alternative considered**: Traditional trained classifier (Decision Tree/Logistic Regression) — valid, but requires a labeled training dataset and training/eval code, more time cost
- **Why this way**: Faster to build correctly in a week, gives reasoning "for free" (see next point)

### "Recommends whether to approve, delay, or reject the deployment"
- **What you build**: A simple decision rule layered on top of the LLM's risk label — Low→approve, Medium→delay/flag, High→reject
- **Tech**: Plain Python if/else logic inside your FastAPI service
- **Alternative considered**: Let the LLM directly output the action too — viable, but keeping the mapping as explicit code makes the decision logic itself auditable and not dependent on LLM phrasing
- **Why this way**: Deterministic, easy to explain, easy to adjust thresholds later (ties into the feedback loop requirement)

### "Integrates with Azure DevOps pipelines and approval gates"
- **What you build**: An Environment Check of type "Invoke REST API" attached to your pipeline's deployment environment, calling your API
- **Tech**: Azure DevOps native "Invoke REST API" check (built-in feature, not a workaround)
- **Alternative considered**: Azure Function/Logic App as the callback target — more "enterprise," adds setup time you don't have
- **Why this way**: This is literally the documented, real mechanism Azure DevOps provides for exactly this use case

### "Provides audit trails and explainable AI decisions for compliance"
- **What you build**: Every decision (input data, risk label, LLM's reasoning text, final action) written as a row to a database
- **Tech**: SQLite
- **Alternative considered**: Azure SQL Database / Cosmos DB — production-grade, but unnecessary setup overhead for a demo scale
- **Why this way**: Same functional guarantee (persistent, queryable records) at zero infrastructure cost

---

## 2. Scope of the Problem — section by section

### 2.1 Data Collection & Feature Engineering
- **Build success/failure rates, test coverage/failure patterns, commit metadata, deployment/stage metrics** → captured as fields in your synthetic dataset generator and real commit pulls
- **Commit complexity, pipeline stage success ratio, recent changes by author/team** → computed fields (e.g. files_changed count, author's last-N-deployments success rate) fed into the LLM prompt as context
- **Deployment environment and stage-level metrics** → add `environment` (staging/production) and `failed_at_stage` (build/test/deploy) as explicit fields — a failure at staging is a different risk signal than a production failure, and the brief separates these
- **Tech**: Python (pandas for shaping data), Azure DevOps REST API
- **Why**: These are exactly the "features" the brief names — nothing invented, nothing omitted

### 2.2 AI-Based Risk Assessment
- **Predict likelihood of failure, assign risk categories** → the Groq LLM call, structured prompt, structured response parsing
- **Explainability — reasoning behind recommendations** → the LLM is explicitly prompted to output a short reasoning string alongside its classification, stored and displayed everywhere the decision appears
- **Tech**: Groq API, prompt engineering, JSON-structured LLM output for reliable parsing
- **Why**: Directly satisfies both scope bullets in one mechanism — no separate explainability layer needed

### 2.3 Approval Workflow Integration
- **Auto-approve low, suggest checks/delay medium, block high until manual review** → your decision-rule logic (see above) plus the response format Azure DevOps expects from an "Invoke REST API" check
- **Tech**: Azure DevOps Check configuration + your API's response payload
- **Why**: One-to-one mapping between the three risk tiers and the three named actions in the brief — nothing extra invented

### 2.4 Feedback Loop & Continuous Learning
- **Collect post-deployment outcomes, retrain periodically, adjust thresholds dynamically** → for the demo, you simulate outcome data being logged (success/fail after the fact) and *explain*, with a working data flow, how this would feed back into either retraining a model or adjusting your decision thresholds
- **Production incidents** → the brief specifically names incidents, not just pass/fail — add an `incident_severity` field (none/minor/major) to the outcome data, not just a binary success/fail. This also strengthens your "reduction in incidents" evaluation story.
- **Tech**: Same SQLite table, extended with `actual_outcome` and `incident_severity` columns; a short script showing threshold adjustment logic as a concept
- **Why honest here**: Full automated retraining scheduling is out of scope for a 1-week demo — you build the *data plumbing* for it and explain the next step clearly, rather than faking a live retrain

### 2.5 Reporting & Dashboard
- **Risk predictions per commit/run, historical approval accuracy (predicted vs actual), trends by project/team** → dashboard reads directly from your SQLite audit table
- **Trends by project or team specifically** → your synthetic data must include a `team` or `project` field (not just author), and the dashboard needs a breakdown/filter view by that field, not just an overall trend line
- **Tech**: Streamlit + pandas for aggregation, basic charts (line/bar), groupby team/project
- **Why**: Directly satisfies the named dashboard requirement and is a separately graded evaluation criterion

### 2.6 Notifications & Communication
- **Notify stakeholders — approvals recommended/blocked, risk insights, post-deployment outcomes** → email sent by your API whenever a decision is made
- **Suggested mitigation steps** → the brief asks for more than "why it's risky" — extend the LLM prompt to also output a short suggested action (e.g. "add integration tests before retry," "get a second reviewer"), included in the email body
- **Post-deployment outcomes for feedback** → this is a *second*, separate notification, not the same email as the decision — trigger a follow-up email once the actual outcome (success/fail/incident) is logged, closing the loop for the reader
- **Tech**: Python `smtplib` (built-in, no external service/approval needed), two distinct email templates (decision-time and outcome-time)
- **Why**: Email is explicitly listed as an acceptable channel in the brief — no need to wait on Teams/Slack webhook approval

### 2.7 Audit & Compliance
- **Logs of AI recommendations, deployment decisions, execution outcomes; explainable and reviewable** → same SQLite table, viewable via the dashboard or direct query
- **Tech**: SQLite (same store used for dashboard + audit — one source of truth, not duplicated)
- **Why**: Single database serving both the dashboard and audit trail avoids inconsistency between "what the dashboard shows" and "what actually happened"

---

## 3. Expected Deliverables — mapped directly

| Deliverable (from brief) | What you'll hand over |
|---|---|
| Architecture diagram | The 5-stage flow diagram (Azure DevOps → API → LLM → decision → log/notify) |
| AI/ML model for risk prediction | Groq LLM integration with structured prompt |
| Azure DevOps pipeline integration with approval gates | Working "Invoke REST API" check wired to your API |
| Dashboard with risk analytics and post-deployment insights | Streamlit dashboard reading from SQLite |
| Notifications and communication workflow | Email-on-decision script |
| Documentation including audit trail and explainability | This document + the SQLite audit log + reasoning strings stored per decision |

---

## 4. Evaluation Criteria — how each is satisfied

| Criterion | How your build satisfies it |
|---|---|
| Accuracy of AI risk prediction | Test the LLM against your simulated dataset's known outcomes, report a simple accuracy figure |
| Correct integration with Azure DevOps approval gates | Live demo of a real gate pausing and resolving based on your API's response |
| Reduction in failed deployments or incidents | Backtest: show how many "would-be failures" in your simulated data the system would have blocked |
| Explainability of AI decisions | Every decision has a stored, human-readable reasoning string — show this live |
| Quality of dashboards and notifications | Live dashboard + a real email received during the demo |
| Practicality and scalability | Talk track: SQLite → Azure SQL, single-pipeline → multi-pipeline via parameterized config, LLM prompt → trained model once real data exists |

---

## 5. Full tech stack summary

| Layer | Tech chosen | Primary alternative | Why chosen over alternative |
|---|---|---|---|
| CI/CD platform | Azure DevOps | — (mandated by brief) | Named explicitly in title and objective |
| API service | Python + FastAPI | Flask, Node/Express | Native ML/data ecosystem, less boilerplate than Flask |
| AI reasoning | Groq (LLM) | Trained scikit-learn model | Faster to build well in 1 week, built-in explainability, POC-approved |
| Hosting | Azure App Service (free tier) | Local + ngrok | Free Azure account already covers it; permanent URL vs. temporary tunnel |
| Database | SQLite | Azure SQL / Cosmos DB | Zero setup, sufficient for demo scale, same functional guarantee |
| Dashboard | Streamlit | React + custom charts | Python-native, fast to build, no separate frontend needed |
| Notifications | Python smtplib (email) | Teams/Slack webhook | No external approval/setup needed, explicitly an acceptable channel |

---

## 6. Considered upgrade — retrieval-augmented prompting

Beyond the base LLM approach, one legitimate strengthening worth mentioning to your POC: instead of only sending the *current* deployment's stats to the LLM, also pull 2-3 of the most similar past deployments from your database and include their real outcomes directly in the prompt. This grounds the LLM's reasoning in actual historical pattern-matching (directly serving the "recent changes by same author or team" requirement) rather than purely general judgment, while remaining just prompt engineering — no new tech stack required. Good to mention as your natural next iteration, not necessary to build for the 1-week demo.

## How to use this in your POC meeting

Walk through it in this order: **objective → scope → deliverables → evaluation criteria → tech stack**. For every tech choice, you can now say "this maps to [specific line], I considered [alternative], I chose this because [reason]" — nothing you're building is arbitrary, and you have paper to point to for every decision.
