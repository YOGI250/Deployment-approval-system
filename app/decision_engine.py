"""
decision_engine.py

Owns the one business rule in this system: given an ML-predicted risk
level, what should happen to the deployment. This is the single place
that mapping lives -- risk_scorer.py calls into this rather than
computing (or letting api.py or Groq compute) its own copy. Future
policy changes (e.g. a new risk tier, a different action for Medium)
should only ever require editing this file.
"""

RISK_TO_DECISION = {
    "Low": "approve",
    "Medium": "delay",
    "High": "reject",
}

# Unrecognized/unexpected risk level fails toward caution (a human
# reviews it) rather than silently approving.
DEFAULT_DECISION = "delay"


def decide_action(risk_level: str) -> str:
    """Converts an ML-predicted risk level into a business decision."""
    return RISK_TO_DECISION.get(risk_level, DEFAULT_DECISION)
