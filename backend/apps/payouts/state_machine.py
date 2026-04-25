"""
Payout state machine.

Legal transitions:
    pending  → processing
    processing → completed
    processing → failed

Terminal states (no outgoing transitions):
    completed
    failed

Any other transition raises InvalidStateTransition. The check happens
at the application layer before the DB write, so invalid states are
caught early and never persisted.
"""
from .exceptions import InvalidStateTransition

VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"processing"},
    "processing": {"completed", "failed"},
    "completed": set(),   # terminal — nothing can leave completed
    "failed": set(),      # terminal — failed → completed is explicitly blocked here
}


def transition(payout, to_status: str) -> None:
    """
    Validate and apply a state transition to a payout instance.

    Mutates `payout.status` in memory but does NOT call `payout.save()`.
    The caller must save within an atomic transaction so the state change
    and any associated ledger entry are committed together or not at all.

    Raises:
        InvalidStateTransition: if the transition is not in VALID_TRANSITIONS.
    """
    allowed = VALID_TRANSITIONS.get(payout.status, set())
    if to_status not in allowed:
        raise InvalidStateTransition(
            f"Cannot transition payout #{payout.pk} "
            f"from '{payout.status}' to '{to_status}'. "
            f"Allowed: {allowed if allowed else 'none — terminal state'}"
        )
    payout.status = to_status
