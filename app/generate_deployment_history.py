"""
generate_deployment_history.py

Purpose: creates a fake (synthetic) dataset of past deployments, standing in
for real historical data we don't have access to yet. This gives our risk
model and dashboard something realistic to work with.

Every field here maps to something specific from the project brief:
- files_changed, lines_changed        -> "commit complexity"
- test_coverage_pct, tests_failed     -> "test results / test failure patterns"
- author, author_recent_success_rate  -> "recent changes by same author"
- team                                -> "trends by project or team"
- environment, failed_at_stage        -> "deployment environment and stage metrics"
- day_of_week, hour                   -> realistic timing risk (e.g. Friday evenings)
- outcome                             -> the actual ground truth (success/fail)
- incident_severity                   -> "production incidents" tracking

Run this once to create deployment_history.csv, which everything else
(the risk prompt, the database, the dashboard) will use for testing.
"""

import csv
import random
import os
from datetime import datetime, timedelta

random.seed(42)  # keeps results the same every time we run this, easier to debug

# Points to the data/ folder regardless of what directory you run this from
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "deployment_history.csv")

AUTHORS = ["priya", "arjun", "meena", "karthik", "divya", "sanjay"]
TEAMS = ["payments", "checkout", "auth", "search", "notifications"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

NUM_ROWS = 500  # 500 fake past deployments


def pick_author_skill():
    """
    Each author gets a hidden 'skill level' that influences their failure
    rate consistently across the dataset -- this is what makes
    'author_recent_success_rate' a meaningful signal instead of noise.
    """
    return random.uniform(0.6, 0.97)  # each author's typical success rate


author_skill = {a: pick_author_skill() for a in AUTHORS}


def generate_row(deployment_id):
    author = random.choice(AUTHORS)
    team = random.choice(TEAMS)

    files_changed = random.randint(1, 100)
    lines_changed = files_changed * random.randint(5, 40)
    test_coverage_pct = round(random.uniform(30, 100), 1)
    tests_failed = random.randint(0, 5) if test_coverage_pct < 70 else random.randint(0, 1)

    day = random.choice(DAYS)
    hour = random.randint(0, 23)
    environment = random.choices(["staging", "production"], weights=[0.4, 0.6])[0]

    # ---- Build the FAILURE PROBABILITY from realistic risk factors ----
    # This is the part that makes the data meaningful rather than random.
    risk_score = 0.03  # baseline risk for any deployment

    if files_changed > 50:
        risk_score += 0.15
    elif files_changed > 20:
        risk_score += 0.05

    if test_coverage_pct < 60:
        risk_score += 0.18
    elif test_coverage_pct < 80:
        risk_score += 0.06

    if tests_failed > 0:
        risk_score += 0.12

    if day in ("Fri", "Sat", "Sun") and hour >= 17:
        risk_score += 0.08  # late Friday/weekend deploys are classic risk factors

    risk_score += (1 - author_skill[author]) * 0.15  # less-consistent authors add risk

    risk_score = min(risk_score, 0.85)

    failed = random.random() < risk_score
    outcome = "fail" if failed else "success"

    failed_at_stage = None
    incident_severity = "none"
    if failed:
        failed_at_stage = random.choices(
            ["build", "test", "deploy"], weights=[0.2, 0.4, 0.4]
        )[0]
        if environment == "production":
            incident_severity = random.choices(
                ["minor", "major"], weights=[0.7, 0.3]
            )[0]

    return {
        "deployment_id": deployment_id,
        "author": author,
        "team": team,
        "files_changed": files_changed,
        "lines_changed": lines_changed,
        "test_coverage_pct": test_coverage_pct,
        "tests_failed": tests_failed,
        "day_of_week": day,
        "hour": hour,
        "environment": environment,
        "outcome": outcome,
        "failed_at_stage": failed_at_stage or "",
        "incident_severity": incident_severity,
    }


def main():
    rows = [generate_row(i + 1) for i in range(NUM_ROWS)]

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    fail_count = sum(1 for r in rows if r["outcome"] == "fail")
    print(f"Generated {NUM_ROWS} rows -> {OUTPUT_PATH}")
    print(f"Failures: {fail_count} ({fail_count / NUM_ROWS:.1%}) -- should look realistic, not 50/50")


if __name__ == "__main__":
    main()
