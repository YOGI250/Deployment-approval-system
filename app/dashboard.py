"""
dashboard.py

Purpose: a visual dashboard showing risk predictions, decisions, and
trends. This is the "Reporting & Dashboard" requirement from the brief.

IMPORTANT: this fetches data from the API's /history endpoint over HTTP,
rather than reading audit_log.db directly. This is intentional -- it means
the dashboard can be hosted as its own separate service (its own Azure App
Service, with no shared file system with the API), and it works correctly
whether you're running everything locally or fully in the cloud.

Install first:
    pip install streamlit pandas requests --break-system-packages

Configure via environment variables (or .env):
    API_BASE_URL - where your API is running, e.g. http://127.0.0.1:8001
                    or your live Azure App Service URL
    API_KEY      - same key the API requires in the X-API-Key header

Run it:
    streamlit run dashboard.py
"""

import os
import streamlit as st
import pandas as pd
import altair as alt
import requests
import env_loader  # loads .env automatically
from accuracy_metrics import compute_approval_accuracy, compute_daily_accuracy

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8001")
API_KEY = os.environ.get("API_KEY", "")

st.set_page_config(page_title="Deployment Risk Dashboard", layout="wide")

RISK_LABELS = {"Low": "🟢 Low", "Medium": "🟡 Medium", "High": "🔴 High"}
DECISION_LABELS = {"approve": "🟢 Approve", "delay": "🟡 Delay", "reject": "🔴 Reject"}


def risk_label(risk_level):
    return RISK_LABELS.get(risk_level, str(risk_level))


def decision_label(decision):
    return DECISION_LABELS.get(decision, str(decision))


def policy_label(overridden):
    return "🟠 Override Applied" if bool(overridden) else "🟢 ML Prediction"


def threshold_label(overridden):
    return "🟠 Escalated" if bool(overridden) else "🟢 Within Bar"


DEPLOYMENT_STATUS_LABELS = {"success": "🟢 Verified Healthy", "failed": "🔴 Verification Failed"}


def deployment_status_label(status):
    """DEV-009: status is None until the pipeline's post-deploy /health check reports back."""
    if not status:
        return "⚪ Not Yet Verified"
    return DEPLOYMENT_STATUS_LABELS.get(status, str(status))


RECOVERY_STATUS_LABELS = {
    "NOT_REQUIRED": "🟢 Healthy -- Deployment Successful",
    "RECOVERY_REQUIRED": "🟠 Recovery Required -- Rollback Recommended",
}


def recovery_status_label(status):
    """DEV-010: status is None until a verification result has been evaluated by recovery_manager."""
    if not status:
        return "⚪ Not Yet Evaluated"
    return RECOVERY_STATUS_LABELS.get(status, str(status))


@st.cache_data(ttl=5)  # re-fetches from the API every 5 seconds, so it stays fresh
def load_data():
    try:
        response = requests.get(
            f"{API_BASE_URL}/history",
            headers={"X-API-Key": API_KEY},
            timeout=10,
        )
        response.raise_for_status()
        return pd.DataFrame(response.json())
    except requests.exceptions.RequestException as e:
        st.error(f"Could not reach the API at {API_BASE_URL}: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=30)  # model facts change rarely -- longer cache than deployment history
def load_model_info():
    try:
        response = requests.get(
            f"{API_BASE_URL}/model-info",
            headers={"X-API-Key": API_KEY},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return None


@st.cache_data(ttl=30)
def load_failure_rate_impact():
    try:
        response = requests.get(
            f"{API_BASE_URL}/failure-rate-impact",
            headers={"X-API-Key": API_KEY},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return None


def model_metric_value(info, key):
    """info is None (API unreachable) or a dict where any field may already
    be the literal "N/A" -- either way, render "N/A" rather than crash."""
    if not info:
        return "N/A"
    value = info.get(key)
    return value if value not in (None, "") else "N/A"


def format_offline_accuracy(value):
    if isinstance(value, (int, float)):
        return f"{value * 100:.1f}%" if value <= 1 else f"{value:.1f}%"
    return "N/A"


def format_ratio_pct(value):
    """value is a 0-1 fraction (precision/recall/FPR/FNR) or None when its
    denominator was 0 -- render "N/A" rather than fabricate 0%."""
    return f"{value * 100:.0f}%" if value is not None else "N/A"


# ---- Header ----
st.title("AI-Powered Deployment Approval Platform")
st.caption("Enterprise Deployment Governance Dashboard")
st.caption("Random Forest  •  Policy Engine  •  Explainable AI  •  Azure DevOps  •  Audit Trail")

# ---- IMP-002: Model Information ----
# Describes the deployed model itself -- independent of df/deployment
# history below, so it renders even with zero logged deployments. Every
# value is either read live from the model artifact/filesystem/metadata
# file, or "N/A" -- never fabricated. See model_info.py.
st.subheader("Model Information")
model_info = load_model_info()
model_row1 = st.columns(4)
model_row1[0].metric("Model Name", model_metric_value(model_info, "model_name"))
model_row1[1].metric("Model Version", model_metric_value(model_info, "model_version"))
model_row1[2].metric("Prompt Version", model_metric_value(model_info, "prompt_version"))
model_row1[3].metric("Number of Features", model_metric_value(model_info, "number_of_features"))

model_row2 = st.columns(3)
model_row2[0].metric("Training Dataset Size", model_metric_value(model_info, "training_dataset_size"))
model_row2[1].metric("Offline Validation Accuracy", format_offline_accuracy(model_info.get("offline_validation_accuracy")) if model_info else "N/A")
model_row2[2].metric("Model Last Updated", model_metric_value(model_info, "model_last_updated"))

st.caption("This information describes the deployed ML model and is independent of live deployment approval accuracy.")
st.divider()

df = load_data()

if df.empty:
    st.info("No deployments logged yet, or the API couldn't be reached. Run a few /predict requests, then refresh this page.")
else:
    # ---- Sidebar filters (audit table only) ----
    st.sidebar.header("Filters")
    st.sidebar.caption("These filters apply to the audit log table only.")

    risk_options = sorted(df["risk_level"].dropna().unique().tolist()) if "risk_level" in df.columns else []
    decision_options = sorted(df["decision"].dropna().unique().tolist()) if "decision" in df.columns else []

    selected_risks = st.sidebar.multiselect("Risk Level", risk_options, default=risk_options)
    selected_decisions = st.sidebar.multiselect("Decision", decision_options, default=decision_options)
    policy_choice = st.sidebar.selectbox("Policy Override", ["All", "Override Applied", "ML Prediction"])
    threshold_choice = st.sidebar.selectbox("Threshold Calibration", ["All", "Escalated", "Within Bar"])

    filtered_df = df.copy()
    if selected_risks:
        filtered_df = filtered_df[filtered_df["risk_level"].isin(selected_risks)]
    if selected_decisions:
        filtered_df = filtered_df[filtered_df["decision"].isin(selected_decisions)]
    if "policy_override" in filtered_df.columns:
        if policy_choice == "Override Applied":
            filtered_df = filtered_df[filtered_df["policy_override"] == 1]
        elif policy_choice == "ML Prediction":
            filtered_df = filtered_df[filtered_df["policy_override"] != 1]
    if "threshold_override" in filtered_df.columns:
        if threshold_choice == "Escalated":
            filtered_df = filtered_df[filtered_df["threshold_override"] == 1]
        elif threshold_choice == "Within Bar":
            filtered_df = filtered_df[filtered_df["threshold_override"] != 1]

    if "team" in df.columns and df["team"].notna().any():
        team_options = sorted(df["team"].dropna().unique().tolist())
        selected_teams = st.sidebar.multiselect("Team", team_options, default=team_options)
        if selected_teams:
            filtered_df = filtered_df[filtered_df["team"].isin(selected_teams)]

    # ---- KPI cards ----
    row1 = st.columns(4)
    row1[0].metric("Total Deployments", len(df))
    row1[1].metric("Approved", int((df["decision"] == "approve").sum()))
    row1[2].metric("Delayed", int((df["decision"] == "delay").sum()))
    row1[3].metric("Rejected", int((df["decision"] == "reject").sum()))

    row2 = st.columns(5)
    if "confidence" in df.columns and df["confidence"].notna().any():
        row2[0].metric("Avg. ML Confidence", f"{df['confidence'].mean() * 100:.0f}%")
    else:
        row2[0].metric("Avg. ML Confidence", "N/A")
    if "policy_override" in df.columns:
        row2[1].metric("Policy Overrides", int((df["policy_override"] == 1).sum()))
    else:
        row2[1].metric("Policy Overrides", "N/A")
    if "threshold_override" in df.columns:
        row2[2].metric("Threshold Escalations", int((df["threshold_override"] == 1).sum()))
    else:
        row2[2].metric("Threshold Escalations", "N/A")
    if "model" in df.columns:
        row2[3].metric("ML Predictions Used", int(df["model"].notna().sum()))
    else:
        row2[3].metric("ML Predictions Used", "N/A")
    latest = df.iloc[0]  # /history returns newest first
    row2[4].metric("Current Model Version", f"{latest.get('model') or 'N/A'} {latest.get('model_version') or ''}".strip())

    # ---- DEV-009: deployment verification KPIs ----
    row3 = st.columns(4)
    if "deployment_status" in df.columns:
        row3[0].metric("Verified Healthy", int((df["deployment_status"] == "success").sum()))
        row3[1].metric("Verification Failed", int((df["deployment_status"] == "failed").sum()))
        row3[2].metric("Not Yet Verified", int(df["deployment_status"].isna().sum()))
    else:
        row3[0].metric("Verified Healthy", "N/A")
        row3[1].metric("Verification Failed", "N/A")
        row3[2].metric("Not Yet Verified", "N/A")
    row3[3].metric("Latest Verification", deployment_status_label(latest.get("deployment_status")))

    # ---- IMP-001: approval accuracy KPIs ----
    # Computed only from rows with a real, verified deployment_status --
    # never hardcoded, estimated, or guessed. See accuracy_metrics.py for
    # the exact correctness definition.
    accuracy = compute_approval_accuracy(df.to_dict("records"))
    st.subheader("Approval Accuracy")
    row4 = st.columns(4)
    row4[0].metric(
        "Approval Accuracy",
        f"{accuracy['accuracy_pct']:.0f}%" if accuracy["accuracy_pct"] is not None else "N/A",
    )
    row4[1].metric("Correct Predictions", accuracy["correct"])
    row4[2].metric("Incorrect Predictions", accuracy["incorrect"])
    row4[3].metric("Verified Deployments", accuracy["total_verified"])
    st.caption("Calculated from verified deployment outcomes only.")

    row5 = st.columns(4)
    row5[0].metric("Precision", format_ratio_pct(accuracy["precision"]))
    row5[1].metric("Recall", format_ratio_pct(accuracy["recall"]))
    row5[2].metric("False Positive Rate", format_ratio_pct(accuracy["false_positive_rate"]))
    row5[3].metric("False Negative Rate", format_ratio_pct(accuracy["false_negative_rate"]))

    if accuracy["total_verified"] > 0:
        accuracy_chart_df = pd.DataFrame({
            "Result": ["Correct", "Incorrect"],
            "Count": [accuracy["correct"], accuracy["incorrect"]],
        })
        accuracy_chart = (
            alt.Chart(accuracy_chart_df)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=60)
            .encode(
                x=alt.X("Result:N", title=None, sort=["Correct", "Incorrect"]),
                y=alt.Y("Count:Q", title="Deployments"),
                color=alt.Color(
                    "Result:N",
                    scale=alt.Scale(domain=["Correct", "Incorrect"], range=["#0ca30c", "#d03b3b"]),
                    legend=None,
                ),
                tooltip=[alt.Tooltip("Result:N", title="Result"), alt.Tooltip("Count:Q", title="Deployments")],
            )
            .properties(height=220)
        )
        st.altair_chart(accuracy_chart, width="stretch")
    else:
        st.caption("No verified deployments yet -- the accuracy chart will appear once outcomes are available.")

    # ---- Confusion Matrix ----
    st.subheader("Confusion Matrix")
    confusion_df = pd.DataFrame(
        [
            [accuracy["true_positive"], accuracy["false_positive"]],
            [accuracy["false_negative"], accuracy["true_negative"]],
        ],
        index=["Approve", "Reject"],
        columns=["Actual: Success", "Actual: Failed"],
    )
    st.dataframe(confusion_df, width="stretch")

    # ---- Accuracy Trend ----
    st.subheader("Accuracy Trend")
    daily_accuracy = compute_daily_accuracy(df.to_dict("records"))
    if daily_accuracy:
        trend_df = pd.DataFrame(daily_accuracy).set_index("date")
        st.line_chart(trend_df["accuracy_pct"])
    else:
        st.caption("No verified deployments yet -- the accuracy trend will appear once daily outcomes are available.")

    # ---- Failure Rate Impact ----
    # "Reduction in failed deployments" from the brief, answered honestly:
    # compares the pre-tool baseline (deployment_history.csv -- 500
    # deployments that shipped with zero AI gating) against the real
    # failure rate among deployments THIS TOOL approved and that have
    # since been verified. See accuracy_metrics.compute_failure_rate_impact.
    st.subheader("Failure Rate Impact")
    impact = load_failure_rate_impact()
    baseline_rate = impact.get("baseline_fail_rate") if impact else None
    actual_rate = impact.get("actual_fail_rate") if impact else None
    reduction = impact.get("reduction_pct") if impact else None
    sample_size = impact.get("sample_size") if impact else 0

    row6 = st.columns(3)
    row6[0].metric("Baseline Failure Rate (pre-tool)", f"{baseline_rate * 100:.0f}%" if baseline_rate is not None else "N/A")
    row6[1].metric("Actual Failure Rate (AI-approved)", f"{actual_rate * 100:.0f}%" if actual_rate is not None else "N/A")
    row6[2].metric(
        "Reduction",
        f"{reduction:+.0f}%" if reduction is not None else "N/A",
        delta=f"{reduction:.0f}%" if reduction is not None else None,
        delta_color="normal",
    )
    if sample_size:
        st.caption(
            f"Actual rate is measured across {sample_size} AI-approved, verified deployment(s). "
            "Baseline is the 500-deployment pre-tool starter history with no AI gating applied."
        )
    else:
        st.caption(
            "No AI-approved deployments have a verified outcome yet -- 'Actual' and 'Reduction' will "
            "populate as real deployments run through /predict and /deployment-verification. "
            "Baseline is the 500-deployment pre-tool starter history with no AI gating applied."
        )

    st.divider()

    # ---- Latest deployment summary ----
    st.subheader("Latest Deployment")
    lat_row1 = st.columns(4)
    lat_row1[0].metric("Deployment ID", str(latest.get("deployment_id") or "N/A"))
    lat_row1[1].metric("Risk Level", risk_label(latest.get("risk_level")))
    lat_row1[2].metric("Decision", decision_label(latest.get("decision")))
    confidence = latest.get("confidence")
    lat_row1[3].metric("ML Confidence", f"{confidence * 100:.0f}%" if pd.notna(confidence) else "N/A")

    lat_row2 = st.columns(4)
    lat_row2[0].metric("Model", str(latest.get("model") or "N/A"))
    lat_row2[1].metric("Policy Status", policy_label(latest.get("policy_override")))
    lat_row2[2].metric("Threshold Status", threshold_label(latest.get("threshold_override")))
    lat_row2[3].metric("Timestamp", str(latest.get("created_at") or "N/A"))

    with st.expander("🤖 AI Explanation (Reasoning)"):
        st.write(latest.get("reasoning") or "No reasoning recorded for this deployment.")

    st.markdown("**Suggested Action**")
    st.info(latest.get("suggested_action") or "No suggested action recorded.")

    st.markdown("**Policy Information**")
    if bool(latest.get("policy_override")):
        st.warning("🟠 Enterprise Policy Override Applied")
        st.write(latest.get("policy_reason") or "No policy override reason recorded.")
        triggered_policies = latest.get("triggered_policies")
        if not isinstance(triggered_policies, list):
            triggered_policies = []
        if triggered_policies:
            st.markdown("\n".join(f"- {policy}" for policy in triggered_policies))
    else:
        st.success("🟢 ML Prediction Accepted (no policy override)")

    st.markdown("**Threshold Calibration**")
    if bool(latest.get("threshold_override")):
        st.warning("🟠 Threshold Calibration Escalation Applied")
        st.write(latest.get("threshold_reason") or "No threshold escalation reason recorded.")
        triggered_thresholds = latest.get("triggered_thresholds")
        if not isinstance(triggered_thresholds, list):
            triggered_thresholds = []
        if triggered_thresholds:
            st.markdown("\n".join(f"- {threshold}" for threshold in triggered_thresholds))
    else:
        st.success("🟢 Meets current threshold bar (no escalation)")

    st.markdown("**Deployment Verification**")
    verification_status = latest.get("deployment_status")
    if verification_status == "success":
        st.success(f"{deployment_status_label(verification_status)} -- checked at {latest.get('verification_time') or 'N/A'}")
    elif verification_status == "failed":
        st.error(f"{deployment_status_label(verification_status)} -- checked at {latest.get('verification_time') or 'N/A'}")
    else:
        st.info(deployment_status_label(verification_status))
    health_check_detail = latest.get("health_check")
    if health_check_detail:
        with st.expander("GET /health response"):
            st.json(health_check_detail)

    st.markdown("**Deployment Recovery Status**")
    recovery_status = latest.get("recovery_status")
    if recovery_status == "RECOVERY_REQUIRED":
        st.warning(recovery_status_label(recovery_status))
        st.write(f"**Recovery Reason:** {latest.get('recovery_reason') or 'N/A'}")
        st.write("**Recommended Action:** Rollback to previous stable deployment or redeploy after fixing the issue.")
        st.caption("No automatic rollback has been performed -- this project has no deployment slots, blue-green, or canary setup to roll back through. Human review is required.")
    elif recovery_status == "NOT_REQUIRED":
        st.success(recovery_status_label(recovery_status))
    else:
        st.info(recovery_status_label(recovery_status))

    st.divider()

    # ---- Charts ----
    st.subheader("Trends")
    chart_row1 = st.columns(2)
    with chart_row1[0]:
        st.caption("Risk Distribution")
        risk_counts = df["risk_level"].value_counts().reindex(["Low", "Medium", "High"]).fillna(0)
        st.bar_chart(risk_counts)
    with chart_row1[1]:
        st.caption("Decision Distribution")
        decision_counts = df["decision"].value_counts()
        st.bar_chart(decision_counts)

    chart_row2 = st.columns(2)
    with chart_row2[0]:
        st.caption("Policy Override Distribution")
        if "policy_override" in df.columns:
            override_counts = df["policy_override"].apply(lambda v: "Override" if v == 1 else "ML Prediction").value_counts()
            st.bar_chart(override_counts)
        else:
            st.caption("No policy override data available yet.")
    with chart_row2[1]:
        st.caption("Threshold Calibration Distribution")
        if "threshold_override" in df.columns:
            threshold_counts = df["threshold_override"].apply(lambda v: "Escalated" if v == 1 else "Within Bar").value_counts()
            st.bar_chart(threshold_counts)
        else:
            st.caption("No threshold calibration data available yet.")

    st.caption("Average Confidence by Risk Level")
    if "confidence" in df.columns and df["confidence"].notna().any():
        confidence_by_risk = df.groupby("risk_level")["confidence"].mean().reindex(["Low", "Medium", "High"])
        st.bar_chart(confidence_by_risk)
    else:
        st.caption("No confidence data available yet.")

    # ---- Predicted vs actual accuracy (only works once outcomes are filled in) ----
    st.subheader("Predicted Risk vs Actual Outcome")
    known_outcomes = df[df["actual_outcome"].notna()]
    if not known_outcomes.empty:
        accuracy_table = known_outcomes.groupby("risk_level")["actual_outcome"].apply(
            lambda outcomes: (outcomes == "fail").mean()
        )
        st.write("Actual failure rate by predicted risk level:")
        st.bar_chart(accuracy_table)
    else:
        st.caption("No actual outcomes recorded yet -- this fills in once deployments are marked success/fail after the fact (the feedback loop).")

    st.divider()

    # ---- Audit log table ----
    st.subheader("Audit Log")

    table_df = filtered_df.copy()
    if "risk_level" in table_df.columns:
        table_df["risk_level"] = table_df["risk_level"].apply(risk_label)
    if "decision" in table_df.columns:
        table_df["decision"] = table_df["decision"].apply(decision_label)
    if "policy_override" in table_df.columns:
        table_df["policy_override"] = table_df["policy_override"].apply(policy_label)
    if "threshold_override" in table_df.columns:
        table_df["threshold_override"] = table_df["threshold_override"].apply(threshold_label)
    if "confidence" in table_df.columns:
        table_df["confidence"] = table_df["confidence"].apply(lambda v: f"{v * 100:.0f}%" if pd.notna(v) else "N/A")
    if "deployment_status" in table_df.columns:
        table_df["deployment_status"] = table_df["deployment_status"].apply(deployment_status_label)
    if "recovery_status" in table_df.columns:
        table_df["recovery_status"] = table_df["recovery_status"].apply(recovery_status_label)
    if "rollback_recommended" in table_df.columns:
        table_df["rollback_recommended"] = table_df["rollback_recommended"].apply(lambda v: "Yes" if v == 1 else "No")

    column_order = [
        "deployment_id", "created_at", "risk_level", "decision", "confidence",
        "policy_override", "threshold_override", "model", "model_version", "team", "environment",
        "author", "suggested_action", "reasoning", "policy_reason",
        "triggered_policies", "threshold_reason", "triggered_thresholds",
        "files_changed", "test_coverage_pct",
        "deployment_status", "verification_time",
        "recovery_status", "rollback_recommended", "recovery_reason",
        "actual_outcome", "incident_severity",
    ]
    display_columns = [c for c in column_order if c in table_df.columns]
    display_names = {
        "deployment_id": "Deployment", "created_at": "Timestamp", "risk_level": "Risk",
        "decision": "Decision", "confidence": "Confidence", "policy_override": "Policy Override",
        "threshold_override": "Threshold Calibration",
        "model": "Model", "model_version": "Model Version", "team": "Team",
        "environment": "Environment", "author": "Author", "suggested_action": "Suggested Action",
        "reasoning": "Reasoning", "policy_reason": "Policy Reason",
        "triggered_policies": "Triggered Policies",
        "threshold_reason": "Threshold Reason", "triggered_thresholds": "Triggered Thresholds",
        "files_changed": "Files Changed",
        "test_coverage_pct": "Test Coverage %",
        "deployment_status": "Deployment Status", "verification_time": "Verified At",
        "recovery_status": "Recovery Status", "rollback_recommended": "Rollback Recommended",
        "recovery_reason": "Recovery Reason",
        "actual_outcome": "Actual Outcome",
        "incident_severity": "Incident Severity",
    }

    st.dataframe(
        table_df[display_columns].rename(columns=display_names),
        width="stretch",
    )
