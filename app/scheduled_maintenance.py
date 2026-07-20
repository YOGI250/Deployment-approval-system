"""
scheduled_maintenance.py

Purpose: bundles the two "learn from real outcomes" jobs the brief asks
for -- model retraining and threshold recalibration -- into one script
that's safe to point a scheduler at, instead of both only ever being run
by hand.

Neither train_model.py nor adjust_thresholds.py changed to make this
work; this is purely an orchestration wrapper so there's one script a
weekly Azure DevOps scheduled pipeline (or cron, or any other scheduler)
can call. See docs/SCHEDULED_MAINTENANCE.md for the pipeline YAML.

Run manually (from app/):
    python3 scheduled_maintenance.py

Each step runs independently -- one failing (e.g. threshold adjustment
hitting a database outage) does not prevent the other from running, and
the exit code reflects whether anything failed so a scheduled pipeline
run can flag it without silently succeeding.
"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # app/ -- for adjust_thresholds

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scheduled_maintenance")


def run_threshold_adjustment() -> bool:
    logger.info("Starting threshold adjustment...")
    try:
        import adjust_thresholds
        adjust_thresholds.main()
        logger.info("Threshold adjustment step completed.")
        return True
    except Exception:
        logger.exception("Threshold adjustment failed -- risk_thresholds.json left untouched.")
        return False


def run_model_retrain() -> bool:
    logger.info("Starting model retrain...")
    try:
        from ml import train_model
        train_model.train()
        logger.info("Model retrain step completed.")
        return True
    except Exception:
        logger.exception("Model retrain failed -- the previously deployed model.pkl was left untouched.")
        return False


def main():
    # Threshold adjustment first (cheap, reads the audit log) then retrain
    # (heavier, rebuilds the classifier) -- order doesn't matter functionally
    # since they read independent data sources, but this keeps the cheap
    # check first so a scheduled run fails fast if the database is down.
    threshold_ok = run_threshold_adjustment()
    retrain_ok = run_model_retrain()

    if threshold_ok and retrain_ok:
        logger.info("Scheduled maintenance completed successfully.")
    else:
        logger.warning("Scheduled maintenance completed with at least one failed step -- see log above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
