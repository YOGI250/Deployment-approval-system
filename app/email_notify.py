"""
email_notify.py

Purpose: sends real emails when a deployment decision is made, and again
when the actual outcome is later known. This satisfies the
"Notifications & Communication" section of the brief.

Setup needed (Gmail-specific):
1. Turn on 2-Step Verification on your Google account
2. Create an "App Password" at https://myaccount.google.com/apppasswords
3. Set two environment variables before running the API:
   export GMAIL_ADDRESS="youraddress@gmail.com"
   export GMAIL_APP_PASSWORD="the-16-char-app-password"

Do NOT use your real Gmail password here -- only the App Password works
for this kind of script-based sending.
"""

import os
import smtplib
import ssl
import env_loader  # loads .env file automatically -- must come before reading env vars
from email.mime.text import MIMEText

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

# Where notifications get sent -- for the demo this can just be your own
# inbox, standing in for "the team's" inbox.
RECIPIENT_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_ADDRESS)


def _send_email(subject: str, body: str):
    """Low-level helper that actually sends the email via Gmail's SMTP server."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("[email_notify] Skipped sending -- GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set.")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
        print(f"[email_notify] Sent: {subject}")
    except Exception as e:
        # never let an email failure break the actual deployment decision
        print(f"[email_notify] Failed to send email: {e}")


def notify_decision(deployment_id: str, risk_level: str, reasoning: str,
                     suggested_action: str, decision: str):
    """Called right after a risk decision is made (piece 1 of the notification requirement)."""
    subject = f"Deployment {deployment_id}: {risk_level} risk -- {decision.upper()}"
    body = f"""Deployment ID: {deployment_id}
Risk level: {risk_level}
Decision: {decision}

Reasoning:
{reasoning}

Suggested action:
{suggested_action}
"""
    _send_email(subject, body)


def notify_outcome(deployment_id: str, actual_outcome: str, incident_severity: str):
    """Called once the real outcome is known (piece 2 -- closes the feedback loop)."""
    subject = f"Deployment {deployment_id}: outcome update -- {actual_outcome.upper()}"
    body = f"""Deployment ID: {deployment_id}
Actual outcome: {actual_outcome}
Incident severity: {incident_severity}

This outcome has been recorded and will be used to review prediction accuracy.
"""
    _send_email(subject, body)


def notify_verification_failure(deployment_id: str, health_check: dict, http_status_code: int):
    """
    DEV-009: called when the post-deployment GET /health check comes back
    unhealthy (or unreachable). Distinct from notify_outcome -- this fires
    minutes after deployment, from the pipeline's verification step, not
    from a human-reported real-world outcome.
    """
    subject = f"Deployment {deployment_id}: VERIFICATION FAILED (health check unhealthy)"
    health_summary = health_check if health_check else "No response body -- /health may be unreachable."
    body = f"""Deployment ID: {deployment_id}
Post-deployment health check FAILED.

HTTP status from GET /health: {http_status_code}
Health check response: {health_summary}

The deployment pipeline has marked this deployment as failed. Investigate
the production service before assuming this deployment is safe.
"""
    _send_email(subject, body)


def notify_recovery_required(deployment_id: str, recovery_reason: str, rollback_recommended: bool,
                              recommended_action: str, health_check: dict):
    """
    DEV-010: called when recovery_manager.evaluate_recovery() decides a
    deployment needs recovery attention -- i.e. the post-deployment
    health check failed. This does NOT mean any rollback has happened;
    it's a request for a human to act (roll back or fix and redeploy).
    """
    subject = "Deployment Recovery Required"
    health_summary = health_check if health_check else "No response body -- /health may be unreachable."
    body = f"""Deployment ID: {deployment_id}
Reason: {recovery_reason}
Rollback Recommended: {rollback_recommended}
Recommended Action: {recommended_action}
Health Check Result: {health_summary}

No automatic rollback has been performed. This deployment requires human review.
"""
    _send_email(subject, body)


if __name__ == "__main__":
    # quick manual test -- run this file directly to send yourself one test email
    notify_decision(
        deployment_id="test-001",
        risk_level="High",
        reasoning="This is a test email to confirm the notification system works.",
        suggested_action="No action needed, this is just a test.",
        decision="reject",
    )
