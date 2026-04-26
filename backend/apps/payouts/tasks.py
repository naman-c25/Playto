"""
Celery tasks for the payout processing pipeline.

process_payout       — picks up a pending payout, simulates bank settlement.
detect_stuck_payouts — periodic: retries payouts stuck in 'processing' > 30s.
cleanup_expired_idempotency_keys — periodic: prunes the idempotency table.

Correctness properties:
- Every state transition and its associated ledger write happen inside a single
  atomic transaction. Either both commit or neither does.
- All payout objects are re-fetched under SELECT FOR UPDATE inside each
  transaction to guard against concurrent modifications (e.g. two beat
  instances running simultaneously).
- The 'hang' simulation outcome does nothing — detect_stuck_payouts handles it,
  which mirrors real bank APIs where a response sometimes never arrives.
"""

import logging
import random
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .exceptions import InvalidStateTransition
from .models import LedgerEntry, Payout
from .state_machine import transition

logger = logging.getLogger(__name__)

# Exponential backoff base for stuck payout retries (seconds)
_BACKOFF_BASE = 5
_MAX_ATTEMPTS = 3
_STUCK_THRESHOLD_SECONDS = 30


@shared_task(
    bind=True,
    name="apps.payouts.tasks.process_payout",
    max_retries=0,   # retries are managed by detect_stuck_payouts, not Celery
    acks_late=True,  # only ack after the task body completes — prevents loss on worker crash
)
def process_payout(self, payout_id: int) -> dict:
    """
    Move a payout from PENDING → PROCESSING, then simulate bank settlement:

        70% → COMPLETED  (debit ledger entry written atomically)
        20% → FAILED     (hold released atomically via status change)
        10% → hang       (stays PROCESSING; detect_stuck_payouts retries it)

    The transition to PROCESSING and the simulation are split across two
    separate transactions intentionally: the first transaction is short and
    just marks the record as in-flight; the second (success/failure) writes
    the final outcome. This mirrors a real implementation where the bank API
    call happens between the two DB writes.
    """
    logger.info("Processing payout id=%s", payout_id)

    try:
        # --- Phase 1: claim the payout (pending → processing) ---
        with transaction.atomic():
            payout = Payout.objects.select_for_update().get(pk=payout_id)

            if payout.status != Payout.PENDING:
                logger.warning(
                    "Payout id=%s is not pending (status=%s), skipping",
                    payout_id,
                    payout.status,
                )
                return {"skipped": True, "status": payout.status}

            transition(payout, Payout.PROCESSING)
            payout.processing_started_at = timezone.now()
            payout.attempt_count += 1
            payout.save()

        # --- Phase 2: simulate the bank API call (outside any transaction) ---
        # In production this would be an HTTP call to a banking partner.
        # Keeping it outside the transaction means we don't hold a DB connection
        # open while waiting on a network call.
        outcome = random.choices(
            population=["success", "failure", "hang"],
            weights=[70, 20, 10],
            k=1,
        )[0]

        logger.info("Payout id=%s bank simulation outcome: %s", payout_id, outcome)

        if outcome == "success":
            _complete_payout(payout_id)
        elif outcome == "failure":
            _fail_payout(payout_id, reason="Bank rejected the transfer (simulated failure)")
        else:
            # 'hang' — do nothing here.
            # detect_stuck_payouts will pick it up after STUCK_THRESHOLD_SECONDS.
            logger.info("Payout id=%s is hanging — awaiting stuck-payout detector", payout_id)

    except Payout.DoesNotExist:
        logger.error("Payout id=%s not found", payout_id)
        return {"error": "not_found"}

    except InvalidStateTransition as exc:
        logger.error("Invalid state transition for payout id=%s: %s", payout_id, exc)
        return {"error": str(exc)}

    except Exception:
        logger.exception("Unexpected error processing payout id=%s", payout_id)
        raise

    return {"outcome": outcome}


def _complete_payout(payout_id: int) -> None:
    """
    Atomically: transition payout to COMPLETED and write the debit ledger entry.

    Both writes are in a single transaction. If anything fails (e.g. DB connection
    drops mid-flight) neither the status change nor the ledger entry persists —
    the payout stays PROCESSING and detect_stuck_payouts will retry it.
    """
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(pk=payout_id)

        # Guard: another process may have already handled this payout
        if payout.status != Payout.PROCESSING:
            logger.warning("Payout id=%s already handled (status=%s)", payout_id, payout.status)
            return

        transition(payout, Payout.COMPLETED)
        payout.completed_at = timezone.now()
        payout.save()

        # Write the debit entry in the same transaction.
        # This is the event that reduces the merchant's net ledger balance.
        # The held amount (implicit in PENDING/PROCESSING status) is simultaneously
        # released because the payout is no longer PENDING or PROCESSING.
        LedgerEntry.objects.create(
            merchant=payout.merchant,
            entry_type=LedgerEntry.DEBIT,
            amount_paise=payout.amount_paise,
            payout=payout,
            description=f"Payout #{payout_id} settled to bank account",
        )


def _fail_payout(payout_id: int, reason: str = "Unknown error") -> None:
    """
    Atomically: transition payout to FAILED and release the held funds.

    'Release' here means: the payout's status changes from PROCESSING to FAILED,
    so it no longer appears in the `held_balance` aggregation
    (which only sums PENDING + PROCESSING payouts). The merchant's available
    balance automatically recovers without any new ledger entry.

    This is correct because the funds were never debited — they were only
    "held" implicitly. Changing status atomically with the save is sufficient.
    """
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(pk=payout_id)

        if payout.status != Payout.PROCESSING:
            logger.warning("Payout id=%s already handled (status=%s)", payout_id, payout.status)
            return

        transition(payout, Payout.FAILED)
        payout.failed_at = timezone.now()
        payout.failure_reason = reason
        payout.save()

        # No ledger entry needed: the held balance is released implicitly
        # because this payout is no longer in PENDING or PROCESSING.
        logger.info("Payout id=%s failed, funds released back to available balance", payout_id)


@shared_task(name="apps.payouts.tasks.detect_stuck_payouts")
def detect_stuck_payouts() -> dict:
    """
    Periodic task (runs every 15 seconds via Celery Beat).

    Finds payouts that have been in PROCESSING for longer than STUCK_THRESHOLD_SECONDS
    and either retries them (with exponential backoff) or fails them after MAX_ATTEMPTS.

    Retry policy:
        attempt_count == 1 → retry after 5s   (5^1)
        attempt_count == 2 → retry after 25s  (5^2)
        attempt_count >= 3 → fail permanently, release funds
    """
    cutoff = timezone.now() - timedelta(seconds=_STUCK_THRESHOLD_SECONDS)

    stuck = list(
        Payout.objects.filter(
            status=Payout.PROCESSING,
            processing_started_at__lt=cutoff,
        ).select_related("merchant")
    )

    retried = 0
    failed = 0

    for payout in stuck:
        if payout.attempt_count >= _MAX_ATTEMPTS:
            logger.warning(
                "Payout id=%s exceeded max attempts (%s), failing permanently",
                payout.pk,
                payout.attempt_count,
            )
            _fail_payout(
                payout.pk,
                reason=f"Max retry attempts ({_MAX_ATTEMPTS}) exceeded — stuck in processing",
            )
            failed += 1
        else:
            # Reset to PENDING so process_payout can claim it again.
            # We do this inside a transaction with a lock to guard against
            # another beat instance doing the same reset simultaneously.
            with transaction.atomic():
                locked = Payout.objects.select_for_update().get(pk=payout.pk)
                if locked.status != Payout.PROCESSING:
                    continue  # already handled by another beat instance
                # Intentionally bypass transition() here.
                # PROCESSING → PENDING is a retry reset, not a forward transition.
                # The state machine only enforces forward movement; the retry
                # mechanism needs to move backward. Calling transition() would
                # raise InvalidStateTransition because "pending" is not in
                # VALID_TRANSITIONS["processing"]. The guard above (status check
                # + lock) provides equivalent safety.
                locked.status = Payout.PENDING
                locked.processing_started_at = None
                locked.save(update_fields=["status", "processing_started_at", "updated_at"])

            countdown = _BACKOFF_BASE ** payout.attempt_count
            process_payout.apply_async(args=[payout.pk], countdown=countdown)
            logger.info(
                "Payout id=%s requeued (attempt %s), retry in %ss",
                payout.pk,
                payout.attempt_count + 1,
                countdown,
            )
            retried += 1

    logger.info("detect_stuck_payouts: retried=%s failed=%s", retried, failed)
    return {"retried": retried, "failed": failed}


@shared_task(name="apps.payouts.tasks.cleanup_expired_idempotency_keys")
def cleanup_expired_idempotency_keys() -> dict:
    """
    Hourly maintenance: delete expired idempotency key records.
    Keeps the table lean — without this it would grow unboundedly.
    """
    from .models import IdempotencyKey

    deleted, _ = IdempotencyKey.objects.filter(expires_at__lt=timezone.now()).delete()
    logger.info("Cleaned up %s expired idempotency keys", deleted)
    return {"deleted": deleted}
