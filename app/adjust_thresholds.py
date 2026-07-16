"""
adjust_thresholds.py

Purpose: implements the brief's "Adjust risk thresholds dynamically based
on pipeline performance" requirement as a real, runnable mechanism, not
just a talking point.

How it works:
1. Reads every audit log row that has a real actual_outcome recorded
   (i.e. the feedback loop has closed on it)
2. Computes the real failure rate within each risk bucket (Low/Medium/High)
3. If Low-risk deployments are failing more often than they should, this
   means the thresholds are too permissive -- tighten them
4. If High-risk deployments are almost never actually failing, this means
   the thresholds are too conservative (blocking things that were fine)
   -- loosen them slightly
5. Writes the updated thresholds back to risk_thresholds.json, with a
   timestamp and a plain-English reason logged for audit purposes

Run manually, or on a schedule (e.g. a weekly Azure DevOps pipeline job):
    python3 adjust_thresholds.py

Requires a reasonable sample size per bucket before adjusting -- with too
little data, random noise could swing thresholds around pointlessly, so
small samples are left alone on purpose.
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_log import get_all_logs, init_db
from risk_scorer import THRESHOLDS_PATH, load_thresholds

MIN_SAMPLES_TO_ADJUST = 10  # don't adjust based on noise from tiny samples

# What we consider an acceptable real failure rate for each risk bucket.
# If Low-risk deployments fail more than this, the bar for "Low" is too
# loose. If High-risk deployments fail LESS than this, the bar for "High"
# is unnecessarily strict and is probably blocking safe deployments.
ACCEPTABLE_FAIL_RATE = {
    "Low": 0.05,     # Low risk should rarely fail
    "High": 0.30,    # High risk should genuinely fail often -- if it's failing
                      # far less than this, we're being overly cautious
}


def compute_bucket_fail_rates(logs: list) -> dict:
    """Groups logged decisions by risk_level and computes real failure rate per bucket."""
    buckets = {"Low": [], "Medium": [], "High": []}
    for row in logs:
        if row.get("actual_outcome") and row.get("risk_level") in buckets:
            buckets[row["risk_level"]].append(1 if row["actual_outcome"] == "fail" else 0)

    fail_rates = {}
    for level, outcomes in buckets.items():
        if outcomes:
            fail_rates[level] = {"fail_rate": sum(outcomes) / len(outcomes), "sample_size": len(outcomes)}
        else:
            fail_rates[level] = {"fail_rate": None, "sample_size": 0}
    return fail_rates


def adjust_thresholds(fail_rates: dict, thresholds: dict) -> tuple:
    """
    Returns (updated_thresholds, reason_string_or_None).
    Makes small, conservative adjustments -- this is meant to nudge
    thresholds over time based on real evidence, not swing wildly.
    """
    reasons = []

    low_stats = fail_rates["Low"]
    if low_stats["sample_size"] >= MIN_SAMPLES_TO_ADJUST and low_stats["fail_rate"] > ACCEPTABLE_FAIL_RATE["Low"]:
        # Low risk is failing more than expected -- tighten the bar to qualify as Low
        old_coverage = thresholds["low"]["min_test_coverage_pct"]
        thresholds["low"]["min_test_coverage_pct"] = min(95, old_coverage + 5)
        old_files = thresholds["low"]["max_files_changed"]
        thresholds["low"]["max_files_changed"] = max(5, old_files - 5)
        reasons.append(
            f"Low-risk deployments failed {low_stats['fail_rate']:.0%} of the time "
            f"(n={low_stats['sample_size']}, target <{ACCEPTABLE_FAIL_RATE['Low']:.0%}) -- "
            f"tightened Low bar: min coverage {old_coverage}%->{thresholds['low']['min_test_coverage_pct']}%, "
            f"max files {old_files}->{thresholds['low']['max_files_changed']}"
        )

    high_stats = fail_rates["High"]
    if high_stats["sample_size"] >= MIN_SAMPLES_TO_ADJUST and high_stats["fail_rate"] < ACCEPTABLE_FAIL_RATE["High"]:
        # High risk is failing far less than expected -- we're over-blocking, loosen slightly
        old_coverage = thresholds["medium"]["min_test_coverage_pct"]
        thresholds["medium"]["min_test_coverage_pct"] = max(40, old_coverage - 5)
        reasons.append(
            f"High-risk deployments only failed {high_stats['fail_rate']:.0%} of the time "
            f"(n={high_stats['sample_size']}, target >{ACCEPTABLE_FAIL_RATE['High']:.0%}) -- "
            f"loosened Medium/High boundary: min coverage {old_coverage}%->{thresholds['medium']['min_test_coverage_pct']}%"
        )

    if not reasons:
        return thresholds, None
    return thresholds, "; ".join(reasons)


def main():
    init_db()
    logs = get_all_logs()
    fail_rates = compute_bucket_fail_rates(logs)

    print("Real failure rates by predicted risk level (from closed-loop outcomes):")
    for level, stats in fail_rates.items():
        if stats["sample_size"]:
            print(f"  {level}: {stats['fail_rate']:.0%} failed (n={stats['sample_size']})")
        else:
            print(f"  {level}: no outcome data yet")

    thresholds = load_thresholds()
    updated, reason = adjust_thresholds(fail_rates, thresholds)

    if reason is None:
        print("\nNo adjustment made -- either not enough data yet, or current thresholds are performing within target ranges.")
        return

    updated["last_adjusted"] = datetime.now().isoformat()
    updated["last_adjusted_reason"] = reason

    with open(THRESHOLDS_PATH, "w") as f:
        json.dump(updated, f, indent=2)

    print(f"\nThresholds adjusted: {reason}")
    print(f"Written to {THRESHOLDS_PATH} -- next /predict call will use the new thresholds immediately.")


if __name__ == "__main__":
    main()
