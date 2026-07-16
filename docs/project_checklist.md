# AI-Powered Deployment Approval Assistant — Build Checklist

## Waiting on POC / Company
- [ ] Answer: LLM-based risk scoring vs. trained ML model
- [ ] Azure DevOps org/project access (Project Administrator or Build/Release Admin rights)
- [ ] Small cloud resource for hosting the API, OR confirmation to use ngrok for the demo
- [ ] Confirm email is fine for notifications (no webhook needed either way)

## Group 1 — Azure DevOps side
- [ ] Create/access Azure DevOps organization + project
- [ ] Create a Git repo with sample/dummy application code
- [ ] Set up a Pipeline (build + test) for that repo
- [ ] Create an Environment (e.g. "Production")
- [ ] Add an "Invoke REST API" Check on that environment

## Group 2 — The AI brain
- [ ] Define what deployment data looks like (commit size, files changed, test results, author, timing)
- [ ] Build the risk-scoring logic (LLM prompt OR trained model — pending POC answer)
- [ ] Make sure it outputs: risk level (Low/Medium/High) + plain-English reasoning

## Group 3 — The connector service
- [ ] Build a small FastAPI service with a `/predict` endpoint
- [ ] Test it standalone (send sample requests, check responses) before touching Azure
- [ ] Make it publicly reachable (cloud host OR ngrok)
- [ ] Wire it into the Azure DevOps "Invoke REST API" check

## Group 4 — Record keeping
- [ ] Set up a SQLite database to log every prediction + decision + reasoning
- [ ] Build a Streamlit dashboard reading from that database
- [ ] Add basic charts: risk over time, approve/delay/block counts

## Group 5 — Notifications
- [ ] Write a Python script to send an email when a deployment is approved/delayed/blocked
- [ ] Test with a real email send before demo day

## Final polish
- [ ] Simulate a "feedback loop" — log fake post-deployment outcomes, explain how retraining would use them
- [ ] Prepare explanation mapped to their evaluation criteria
- [ ] Dry run the full demo end to end
