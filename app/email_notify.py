"""
email_notify.py

Purpose: sends real emails when a deployment decision is made, and again
when the actual outcome is later known. This satisfies the
"Notifications & Communication" section of the brief.

Emails are sent as HTML (with a plain-text fallback for clients that don't
render HTML) so a reviewer opening one in Gmail/Outlook sees a clearly
formatted, color-coded notification instead of a raw text dump.

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
from datetime import datetime, timezone
import env_loader  # loads .env file automatically -- must come before reading env vars
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

# Where notifications get sent -- for the demo this can just be your own
# inbox, standing in for "the team's" inbox.
RECIPIENT_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_ADDRESS)

# Color-coding used across every email so a reviewer recognizes severity
# at a glance without reading the body -- same colors the dashboard uses.
_COLORS = {
    "Low": "#16a34a", "approve": "#16a34a", "success": "#16a34a", "healthy": "#16a34a",
    "Medium": "#d97706", "delay": "#d97706",
    "High": "#dc2626", "reject": "#dc2626", "fail": "#dc2626", "failed": "#dc2626",
    "unhealthy": "#dc2626",
    "neutral": "#4b5563",
}


def _color_for(label: str) -> str:
    return _COLORS.get(label, _COLORS["neutral"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _badge(text: str, color: str) -> str:
    return (
        f'<span style="display:inline-block;padding:4px 14px;border-radius:12px;'
        f'background:{color};color:#ffffff;font-size:13px;font-weight:600;'
        f'font-family:Arial,Helvetica,sans-serif;">{text}</span>'
    )


def _field_rows(fields: list) -> str:
    """fields: list of (label, value) tuples, value=None rows are skipped."""
    rows = ""
    for label, value in fields:
        if value in (None, ""):
            continue
        rows += (
            '<tr>'
            f'<td style="padding:6px 12px 6px 0;color:#6b7280;font-size:13px;'
            f'font-family:Arial,Helvetica,sans-serif;white-space:nowrap;vertical-align:top;">{label}</td>'
            f'<td style="padding:6px 0;color:#111827;font-size:14px;'
            f'font-family:Arial,Helvetica,sans-serif;">{value}</td>'
            '</tr>'
        )
    return f'<table role="presentation" style="border-collapse:collapse;width:100%;">{rows}</table>'


def _section(heading: str, body: str) -> str:
    return (
        f'<div style="margin-top:20px;">'
        f'<div style="font-size:12px;font-weight:700;color:#6b7280;text-transform:uppercase;'
        f'letter-spacing:0.05em;font-family:Arial,Helvetica,sans-serif;margin-bottom:6px;">{heading}</div>'
        f'<div style="font-size:14px;color:#111827;line-height:1.5;font-family:Arial,Helvetica,sans-serif;'
        f'white-space:pre-line;">{body}</div>'
        f'</div>'
    )


def _wrap(badge_html: str, title: str, fields_html: str, sections_html: str, footnote: str = "") -> str:
    return f"""\
<div style="background:#f3f4f6;padding:24px 12px;font-family:Arial,Helvetica,sans-serif;">
  <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;
              border:1px solid #e5e7eb;">
    <div style="background:#111827;padding:18px 24px;">
      <span style="color:#ffffff;font-size:15px;font-weight:700;">Deployment Approval Assistant</span>
    </div>
    <div style="padding:24px;">
      {badge_html}
      <h2 style="margin:14px 0 16px;font-size:19px;color:#111827;">{title}</h2>
      {fields_html}
      {sections_html}
      {f'<div style="margin-top:20px;padding:12px 14px;background:#fef3c7;border-radius:6px;font-size:13px;color:#92400e;">{footnote}</div>' if footnote else ''}
    </div>
    <div style="padding:14px 24px;background:#f9fafb;border-top:1px solid #e5e7eb;
                font-size:12px;color:#9ca3af;">
      Automated notification &middot; {_now()}
    </div>
  </div>
</div>
"""


def _send_email(subject: str, html_body: str, text_body: str):
    """Low-level helper that sends an HTML email with a plain-text fallback via Gmail's SMTP server."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("[email_notify] Skipped sending -- GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL
    # Plain text first, HTML second -- clients render the last part they support,
    # so HTML wins where supported and plain text remains the fallback.
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

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
                     suggested_action: str, decision: str, author: str = None,
                     team: str = None, environment: str = None, confidence: float = None,
                     policy_override: bool = False, policy_reason: str = None,
                     triggered_policies: list = None):
    """Called right after a risk decision is made (piece 1 of the notification requirement)."""
    subject = f"Deployment {deployment_id}: {risk_level} risk -- {decision.upper()}"

    fields = _field_rows([
        ("Deployment ID", deployment_id),
        ("Author", author),
        ("Team", team),
        ("Environment", environment),
        ("Confidence", f"{confidence:.0%}" if confidence is not None else None),
    ])

    sections = _section("Reasoning", reasoning)
    sections += _section("Suggested Action", suggested_action)

    footnote = ""
    if policy_override:
        policies = ", ".join(triggered_policies) if triggered_policies else "an organizational policy"
        footnote = f"Enterprise policy override applied ({policies}): {policy_reason or 'see audit log for details'}."

    html_body = _wrap(
        badge_html=_badge(f"{risk_level.upper()} RISK &middot; {decision.upper()}", _color_for(risk_level)),
        title="Deployment Risk Decision",
        fields_html=fields,
        sections_html=sections,
        footnote=footnote,
    )

    text_body = f"""DEPLOYMENT RISK DECISION
{'-' * 40}
Deployment ID: {deployment_id}
Risk level:    {risk_level}
Decision:      {decision.upper()}
{f'Author:        {author}' if author else ''}
{f'Team:          {team}' if team else ''}
{f'Environment:   {environment}' if environment else ''}
{f'Confidence:    {confidence:.0%}' if confidence is not None else ''}

Reasoning:
{reasoning}

Suggested action:
{suggested_action}
{f"{chr(10)}Policy override: {policy_reason}" if policy_override else ''}
"""
    _send_email(subject, html_body, text_body)


def notify_outcome(deployment_id: str, actual_outcome: str, incident_severity: str):
    """Called once the real outcome is known (piece 2 -- closes the feedback loop)."""
    subject = f"Deployment {deployment_id}: outcome update -- {actual_outcome.upper()}"

    fields = _field_rows([
        ("Deployment ID", deployment_id),
        ("Actual Outcome", actual_outcome.capitalize()),
        ("Incident Severity", incident_severity.capitalize() if incident_severity else None),
    ])
    sections = _section(
        "What happens next",
        "This outcome has been recorded and will be used to review prediction accuracy.",
    )

    html_body = _wrap(
        badge_html=_badge(actual_outcome.upper(), _color_for(actual_outcome)),
        title="Deployment Outcome Recorded",
        fields_html=fields,
        sections_html=sections,
    )

    text_body = f"""DEPLOYMENT OUTCOME RECORDED
{'-' * 40}
Deployment ID:      {deployment_id}
Actual outcome:     {actual_outcome}
Incident severity:  {incident_severity}

This outcome has been recorded and will be used to review prediction accuracy.
"""
    _send_email(subject, html_body, text_body)


def notify_verification_failure(deployment_id: str, health_check: dict, http_status_code: int):
    """
    DEV-009: called when the post-deployment GET /health check comes back
    unhealthy (or unreachable). Distinct from notify_outcome -- this fires
    minutes after deployment, from the pipeline's verification step, not
    from a human-reported real-world outcome.
    """
    subject = f"Deployment {deployment_id}: VERIFICATION FAILED (health check unhealthy)"
    health_summary = health_check if health_check else "No response body -- /health may be unreachable."

    fields = _field_rows([
        ("Deployment ID", deployment_id),
        ("HTTP Status", http_status_code),
    ])
    sections = _section("Health Check Response", str(health_summary))
    sections += _section(
        "Next step",
        "The deployment pipeline has marked this deployment as failed. "
        "Investigate the production service before assuming this deployment is safe.",
    )

    html_body = _wrap(
        badge_html=_badge("VERIFICATION FAILED", _color_for("unhealthy")),
        title="Post-Deployment Health Check Failed",
        fields_html=fields,
        sections_html=sections,
    )

    text_body = f"""POST-DEPLOYMENT HEALTH CHECK FAILED
{'-' * 40}
Deployment ID:  {deployment_id}
HTTP status:    {http_status_code}
Health check:   {health_summary}

The deployment pipeline has marked this deployment as failed. Investigate
the production service before assuming this deployment is safe.
"""
    _send_email(subject, html_body, text_body)


def notify_recovery_required(deployment_id: str, recovery_reason: str, rollback_recommended: bool,
                              recommended_action: str, health_check: dict):
    """
    DEV-010: called when recovery_manager.evaluate_recovery() decides a
    deployment needs recovery attention -- i.e. the post-deployment
    health check failed. This does NOT mean any rollback has happened;
    it's a request for a human to act (roll back or fix and redeploy).
    """
    subject = f"Deployment {deployment_id}: Recovery Required"
    health_summary = health_check if health_check else "No response body -- /health may be unreachable."

    fields = _field_rows([
        ("Deployment ID", deployment_id),
        ("Rollback Recommended", "Yes" if rollback_recommended else "No"),
    ])
    sections = _section("Reason", recovery_reason)
    sections += _section("Recommended Action", recommended_action)
    sections += _section("Health Check Response", str(health_summary))

    html_body = _wrap(
        badge_html=_badge("RECOVERY REQUIRED", _color_for("fail")),
        title="Deployment Recovery Required",
        fields_html=fields,
        sections_html=sections,
        footnote="No automatic rollback has been performed. This deployment requires human review.",
    )

    text_body = f"""DEPLOYMENT RECOVERY REQUIRED
{'-' * 40}
Deployment ID:         {deployment_id}
Reason:                {recovery_reason}
Rollback Recommended:  {rollback_recommended}
Recommended Action:    {recommended_action}
Health Check Result:   {health_summary}

No automatic rollback has been performed. This deployment requires human review.
"""
    _send_email(subject, html_body, text_body)


if __name__ == "__main__":
    # quick manual test -- run this file directly to send yourself one test email
    notify_decision(
        deployment_id="test-001",
        risk_level="High",
        reasoning="This is a test email to confirm the notification system works.",
        suggested_action="No action needed, this is just a test.",
        decision="reject",
        author="test-author",
        team="platform",
        environment="production",
        confidence=0.91,
        policy_override=True,
        policy_reason="Critical files touched with coverage below threshold.",
        triggered_policies=["rule_3_global_critical_file_coverage"],
    )
