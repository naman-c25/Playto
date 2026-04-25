import uuid
from datetime import timedelta

from django.db import models
from django.utils import timezone


def _idempotency_key_expiry():
    """24-hour TTL for idempotency keys, as required."""
    return timezone.now() + timedelta(hours=24)


class LedgerEntry(models.Model):
    """
    Immutable financial event log for a merchant.

    Design decisions:
    - amount_paise is always a positive BigIntegerField. Sign is determined
      by entry_type, never by a negative number in the column. This makes
      aggregation queries unambiguous and avoids sign-flip bugs.
    - Balance is NEVER stored on the Merchant model. It is always derived
      by querying this table, so it cannot drift out of sync.
    - Debits are only written on payout COMPLETION, not on payout creation.
      Pending/processing payouts contribute to 'held' balance, tracked
      separately via the Payout table.
    """

    CREDIT = "credit"
    DEBIT = "debit"
    ENTRY_TYPE_CHOICES = [
        (CREDIT, "Credit"),
        (DEBIT, "Debit"),
    ]

    merchant = models.ForeignKey(
        "merchants.Merchant",
        on_delete=models.CASCADE,
        related_name="ledger_entries",
    )
    entry_type = models.CharField(max_length=6, choices=ENTRY_TYPE_CHOICES)
    amount_paise = models.BigIntegerField()  # always positive — never a float; INR paise

    # USD origin fields — populated for customer payment credits only.
    # Storing both the original USD amount and the rate used locks in the
    # exact conversion that was applied, so historical entries are auditable
    # even if the live rate has since moved.
    usd_cents = models.BigIntegerField(null=True, blank=True)   # original payment in USD cents
    exchange_rate = models.DecimalField(                         # INR per 1 USD at time of credit
        max_digits=10, decimal_places=4, null=True, blank=True
    )

    description = models.TextField()
    payout = models.ForeignKey(
        "Payout",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["merchant", "-created_at"]),
        ]
        constraints = [
            # DB-level guard: amount_paise must always be positive.
            # Enforces the invariant at the storage layer — no application bug
            # can ever write a zero or negative amount into the ledger.
            models.CheckConstraint(
                check=models.Q(amount_paise__gt=0),
                name="ledger_amount_paise_positive",
            ),
        ]

    def save(self, *args, **kwargs):
        # Ledger entries are immutable once written. Any attempt to update
        # an existing entry is a bug — raise hard so it can never go silent.
        if self.pk is not None:
            raise RuntimeError(
                "LedgerEntry is immutable. Updates are not allowed. "
                "Correct the balance by writing a new offsetting entry."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError(
            "LedgerEntry is immutable. Deletions are not allowed. "
            "The ledger is the source of truth and must never lose entries."
        )

    def __str__(self) -> str:
        sign = "+" if self.entry_type == self.CREDIT else "-"
        return f"{sign}{self.amount_paise} paise — {self.merchant.name}"


class Payout(models.Model):
    """
    A merchant's request to withdraw accumulated balance to their bank account.

    State machine (enforced in state_machine.py):
        pending → processing → completed
                             → failed

    'held' balance is implicit: the sum of all pending+processing payout
    amounts is subtracted from total ledger balance to get available balance.
    No separate hold/release ledger entries are written — the status itself
    is the source of truth for what's held.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (PROCESSING, "Processing"),
        (COMPLETED, "Completed"),
        (FAILED, "Failed"),
    ]

    merchant = models.ForeignKey(
        "merchants.Merchant",
        on_delete=models.CASCADE,
        related_name="payouts",
    )
    bank_account = models.ForeignKey(
        "merchants.BankAccount",
        on_delete=models.PROTECT,  # never delete an account with payout history
        related_name="payouts",
    )
    amount_paise = models.BigIntegerField()  # always positive BigInteger, never float
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    idempotency_key = models.UUIDField(db_index=True)
    attempt_count = models.IntegerField(default=0)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["merchant", "status"]),
            # Needed by detect_stuck_payouts periodic task
            models.Index(fields=["status", "processing_started_at"]),
        ]

    def __str__(self) -> str:
        return f"Payout #{self.pk} [{self.status}] {self.amount_paise} paise — {self.merchant.name}"


class IdempotencyKey(models.Model):
    """
    Deduplication record keyed on (merchant, client-supplied UUID).

    Protocol:
    1. Client sends Idempotency-Key header with a UUID.
    2. Server attempts INSERT of a new record (response_body=NULL means in-flight).
    3. If INSERT succeeds → process the request, then write response_body + response_status.
    4. If INSERT fails with IntegrityError → key seen before:
         - response_body is not NULL → return cached response (idempotent replay).
         - response_body is NULL     → first request still in-flight → 409.

    Keys are scoped per merchant: the same UUID from two different merchants
    creates two separate records (unique_together enforces this).
    Keys expire after 24 hours (expires_at) and are cleaned up by a periodic task.
    """

    merchant = models.ForeignKey(
        "merchants.Merchant",
        on_delete=models.CASCADE,
        related_name="idempotency_keys",
    )
    key = models.UUIDField()
    request_body = models.JSONField()
    response_body = models.JSONField(null=True, blank=True)   # NULL = in-flight
    response_status = models.IntegerField(null=True, blank=True)
    payout = models.ForeignKey(
        Payout,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="idempotency_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_idempotency_key_expiry)

    class Meta:
        # Database-level uniqueness — handles concurrent duplicate inserts atomically
        unique_together = [("merchant", "key")]
        indexes = [
            models.Index(fields=["expires_at"]),  # fast cleanup queries
        ]

    def __str__(self) -> str:
        return f"IdempotencyKey {self.key} — {self.merchant.name}"

    @property
    def is_completed(self) -> bool:
        return self.response_status is not None

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at
