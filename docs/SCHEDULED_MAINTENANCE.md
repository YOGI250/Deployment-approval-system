# Scheduling model retraining & threshold adjustment

`app/scheduled_maintenance.py` runs both "learn from real outcomes" jobs
the brief asks for -- model retraining (`train_model.py`) and threshold
recalibration (`adjust_thresholds.py`) -- in one call. It works today,
run by hand:

```
cd app
python3 scheduled_maintenance.py
```

That satisfies "retrain periodically" and "adjust thresholds dynamically"
functionally, but not yet *automatically* -- nothing currently invokes it
on a schedule.

## Automatic scheduling: GitHub Actions, on this repo

Implemented at `.github/workflows/scheduled-maintenance.yml` -- a
weekly (`0 3 * * 1`, every Monday 03:00 UTC) cron-triggered workflow,
plus `workflow_dispatch` for a manual run.

This does **not** live in the Azure DevOps pipeline
(`deployment-approval-demo`) that runs the per-deployment risk check.
That pipeline repo is a separate, minimal "sample project" used only to
trigger `/predict` on the deployed AI service -- it doesn't contain
`train_model.py`, `adjust_thresholds.py`, or `data/model.pkl` at all.
This repo (`deployment-approval-assistant`, on GitHub) is what holds
that code and *is* the thing deployed to the Azure Web App, via App
Service's own git-based deploy (see `.deployment`) -- so GitHub Actions
running directly on it, with no cross-repo checkout, is the simplest
correct place for this job.

The workflow checks out this repo, installs `requirements.txt`,
regenerates `data/deployment_history.csv` (gitignored, seeded with
`random.seed(42)` so it's identical every run -- `train_model.py` blends
real audit-log outcomes on top of it), runs `app/scheduled_maintenance.py`,
then commits `data/model.pkl` and
`data/risk_thresholds.json` back to `main` if either changed (using the
job's own `GITHUB_TOKEN`, via `permissions: contents: write` --
`skip ci` in the commit message to avoid any push-triggered workflow
loop). Committing them is the simplest way to make an updated model
"the one that's live" without a separate model registry -- the next
push to `main` triggers App Service's own deploy and picks up whatever
was just committed. If a real model registry/artifact store exists
later, swap that step for a registry push instead of a git commit.

Requires two repo secrets (Settings -> Secrets and variables -> Actions):
- `DATABASE_URL` -- same Neon Postgres connection string the app itself uses
- `GROQ_API_KEY` -- only needed because `risk_scorer.py` (imported by
  `adjust_thresholds.py`) constructs a Groq client at import time; Groq
  is never actually called during maintenance

## Why weekly

`adjust_thresholds.py` requires at least `MIN_SAMPLES_TO_ADJUST = 10`
outcomes in a risk bucket before it changes anything -- running it daily
against a low-traffic pipeline would mostly be a no-op. Weekly is a
reasonable default; tighten it once real deployment volume is known.
