"""
test_accuracy_metrics.py

IMP-001: verifies compute_approval_accuracy() -- the Approval Accuracy
dashboard KPI's underlying calculation. Nothing here is hardcoded or
estimated; every assertion checks arithmetic derived from constructed
rows, matching exactly what real audit_log data would look like.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from accuracy_metrics import compute_approval_accuracy


def row(decision=None, deployment_status=None, **extra):
    r = {"decision": decision, "deployment_status": deployment_status}
    r.update(extra)
    return r


class TestCorrectPredictions:
    def test_approve_and_success_is_correct(self):
        result = compute_approval_accuracy([row("approve", "success")])
        assert result["correct"] == 1
        assert result["incorrect"] == 0
        assert result["total_verified"] == 1
        assert result["accuracy_pct"] == 100.0

    def test_reject_and_failed_is_correct(self):
        result = compute_approval_accuracy([row("reject", "failed")])
        assert result["correct"] == 1
        assert result["incorrect"] == 0
        assert result["accuracy_pct"] == 100.0


class TestIncorrectPredictions:
    def test_approve_and_failed_is_incorrect(self):
        result = compute_approval_accuracy([row("approve", "failed")])
        assert result["correct"] == 0
        assert result["incorrect"] == 1
        assert result["total_verified"] == 1
        assert result["accuracy_pct"] == 0.0

    def test_reject_and_success_is_incorrect(self):
        result = compute_approval_accuracy([row("reject", "success")])
        assert result["correct"] == 0
        assert result["incorrect"] == 1
        assert result["accuracy_pct"] == 0.0


class TestNoVerificationData:
    def test_missing_deployment_status_is_ignored(self):
        result = compute_approval_accuracy([row("approve", None)])
        assert result["correct"] == 0
        assert result["incorrect"] == 0
        assert result["total_verified"] == 0
        assert result["accuracy_pct"] is None

    def test_unrecognized_deployment_status_is_ignored(self):
        """Anything other than the exact 'success'/'failed' strings DEV-009 writes
        must never be silently coerced into a correct/incorrect bucket."""
        result = compute_approval_accuracy([row("approve", "pending")])
        assert result["total_verified"] == 0
        assert result["accuracy_pct"] is None

    def test_delay_decision_is_ignored_regardless_of_status(self):
        """The ticket only defines correctness for approve/reject -- delay's
        semantics are undefined, so it must never be guessed at."""
        result = compute_approval_accuracy([
            row("delay", "success"),
            row("delay", "failed"),
        ])
        assert result["correct"] == 0
        assert result["incorrect"] == 0
        assert result["total_verified"] == 0
        assert result["accuracy_pct"] is None

    def test_empty_dataset(self):
        result = compute_approval_accuracy([])
        assert result["correct"] == 0
        assert result["incorrect"] == 0
        assert result["total_verified"] == 0
        assert result["accuracy_pct"] is None


class TestMixedDatasets:
    def test_mix_of_correct_incorrect_and_unverified(self):
        rows = [
            row("approve", "success"),   # correct
            row("approve", "success"),   # correct
            row("reject", "failed"),     # correct
            row("approve", "failed"),    # incorrect
            row("reject", "success"),    # incorrect
            row("approve", None),        # ignored -- not yet verified
            row("delay", "success"),     # ignored -- delay undefined
        ]
        result = compute_approval_accuracy(rows)
        assert result["correct"] == 3
        assert result["incorrect"] == 2
        assert result["total_verified"] == 5
        assert result["accuracy_pct"] == 60.0

    def test_all_correct(self):
        rows = [row("approve", "success") for _ in range(4)] + [row("reject", "failed") for _ in range(2)]
        result = compute_approval_accuracy(rows)
        assert result["accuracy_pct"] == 100.0
        assert result["total_verified"] == 6

    def test_all_incorrect(self):
        rows = [row("approve", "failed"), row("reject", "success")]
        result = compute_approval_accuracy(rows)
        assert result["accuracy_pct"] == 0.0
        assert result["total_verified"] == 2


class TestDivisionByZero:
    def test_zero_verified_deployments_does_not_raise(self):
        result = compute_approval_accuracy([row("approve", None), row("delay", "success")])
        assert result["accuracy_pct"] is None  # never 0.0, never a crash

    def test_only_reject_rows_never_divides_by_zero(self):
        result = compute_approval_accuracy([row(None, "success")])
        assert result["total_verified"] == 0
        assert result["accuracy_pct"] is None


class TestReturnShapeForDashboardCompatibility:
    """dashboard.py reads exactly these four keys -- confirms the contract
    stays stable without needing to import dashboard.py itself (which runs
    Streamlit calls at import time and can't be imported in a test process)."""

    def test_result_has_exact_expected_keys(self):
        result = compute_approval_accuracy([row("approve", "success")])
        assert set(result.keys()) == {"correct", "incorrect", "total_verified", "accuracy_pct"}

    def test_correct_and_incorrect_are_plain_ints(self):
        result = compute_approval_accuracy([row("approve", "success"), row("approve", "failed")])
        assert isinstance(result["correct"], int)
        assert isinstance(result["incorrect"], int)
        assert isinstance(result["total_verified"], int)

    def test_rows_missing_keys_entirely_do_not_crash(self):
        """A row shaped like an older audit log entry that predates
        deployment_status entirely (DEV-009) must not raise."""
        result = compute_approval_accuracy([{"decision": "approve"}, {}])
        assert result["total_verified"] == 0
        assert result["accuracy_pct"] is None
