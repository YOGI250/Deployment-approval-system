"""
feature_engineering.py

Converts raw deployment metadata into the named numeric feature dict
consumed by the ML risk model (app/ml/). Framework-independent: no
FastAPI, no Groq, no database imports, no dependency on api.py or
risk_scorer.py. Wired into the live /predict flow via
risk_scorer.score_deployment() -- see app/ml/train_model.py and
app/ml/predictor.py for how the resulting features are used.

Both training (bulk, from deployment_history.csv rows) and future
inference (a single live deployment) go through build_features() so
the two paths can never compute features differently.
"""

# Same substring-based critical-file classifier concept used by
# risk_scorer.py, duplicated here (not imported) so this module has no
# dependency on the Groq-based module it's eventually meant to replace.
CRITICAL_FILE_PATTERNS = [
    "payment", "billing", "auth", "login", "security", "credential",
    "secret", ".env", "config", "migration", "schema",
]

# Decision #8 (approved): unknown/new author success rate defaults to
# 0.5 (neutral), not 1.0 (perfect) and not 0.0 (worst).
DEFAULT_AUTHOR_SUCCESS_RATE = 0.5

# Same reasoning as DEFAULT_AUTHOR_SUCCESS_RATE, applied to a brand-new
# or unrecognized team.
DEFAULT_TEAM_SUCCESS_RATE = 0.5

# Historical training rows have no pipeline_stage_success_ratio column;
# live callers may also omit it. Neutral default for the same reason.
DEFAULT_PIPELINE_STAGE_SUCCESS_RATIO = 0.5


def has_critical_files(changed_files: list) -> bool:
    """True if any changed file path matches a critical-area pattern."""
    if not changed_files:
        return False
    return any(
        pattern in f.lower()
        for f in changed_files
        for pattern in CRITICAL_FILE_PATTERNS
    )


def is_risky_timing(day_of_week: str, hour) -> bool:
    """Friday/Saturday/Sunday at or after 17:00 -- same rule risk_scorer's prompt uses."""
    try:
        hour = int(hour)
    except (TypeError, ValueError):
        return False
    return day_of_week in ("Fri", "Sat", "Sun") and hour >= 17


def calculate_author_success_rate(author: str, history_rows: list) -> float:
    """
    % of this author's past deployments that succeeded, from history_rows.
    Returns DEFAULT_AUTHOR_SUCCESS_RATE when the author has no history,
    rather than treating a brand-new author as a perfect track record.
    """
    author_rows = [r for r in history_rows if r.get("author") == author]
    if not author_rows:
        return DEFAULT_AUTHOR_SUCCESS_RATE
    successes = sum(1 for r in author_rows if r.get("outcome") == "success")
    return round(successes / len(author_rows), 2)


def calculate_team_success_rate(team: str, history_rows: list) -> float:
    """
    % of this team's past deployments that succeeded, from history_rows.
    Mirrors calculate_author_success_rate -- same reasoning, one level
    up: a team's own recent track record is a distinct signal from any
    single author's, since a team can absorb one risky author's history
    or, symmetrically, be dragged down by it.
    """
    team_rows = [r for r in history_rows if r.get("team") == team]
    if not team_rows:
        return DEFAULT_TEAM_SUCCESS_RATE
    successes = sum(1 for r in team_rows if r.get("outcome") == "success")
    return round(successes / len(team_rows), 2)


def build_features(deployment: dict, history_rows: list = None) -> dict:
    """
    Turns one deployment's raw metadata into the named numeric feature
    dict the ML model expects.

    `history_rows` is used only to derive author_recent_success_rate
    when the caller hasn't already computed it. If `deployment` already
    has an "author_recent_success_rate" key (e.g. a live caller that
    computed it against combined real+synthetic history), that value is
    used as-is and history_rows is ignored for this purpose.
    """
    history_rows = history_rows or []

    author_success_rate = deployment.get("author_recent_success_rate")
    if author_success_rate is None:
        author_success_rate = calculate_author_success_rate(
            deployment.get("author"), history_rows
        )

    team_success_rate = deployment.get("team_recent_success_rate")
    if team_success_rate is None:
        team_success_rate = calculate_team_success_rate(
            deployment.get("team"), history_rows
        )

    pipeline_ratio = deployment.get("pipeline_stage_success_ratio")
    if pipeline_ratio is None:
        pipeline_ratio = DEFAULT_PIPELINE_STAGE_SUCCESS_RATIO

    return {
        "files_changed": float(deployment.get("files_changed", 0) or 0),
        "lines_changed": float(deployment.get("lines_changed", 0) or 0),
        "test_coverage_pct": float(deployment.get("test_coverage_pct", 0) or 0),
        "tests_failed": float(deployment.get("tests_failed", 0) or 0),
        "author_recent_success_rate": float(author_success_rate),
        "team_recent_success_rate": float(team_success_rate),
        "has_critical_files": 1.0 if has_critical_files(deployment.get("changed_files")) else 0.0,
        "is_risky_timing": 1.0 if is_risky_timing(deployment.get("day_of_week"), deployment.get("hour")) else 0.0,
        "is_production": 1.0 if deployment.get("environment") == "production" else 0.0,
        "pipeline_stage_success_ratio": float(pipeline_ratio),
    }
