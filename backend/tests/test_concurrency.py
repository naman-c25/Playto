"""
Concurrency test: two simultaneous payout requests for more than the available balance.

Scenario: Merchant has ₹100 (10,000 paise). Two threads simultaneously request
₹60 (6,000 paise) each. Exactly one must succeed; the other must be rejected with
402 Insufficient Funds. No overdraft must be possible.

This test is the most important correctness signal in the codebase. It exercises
the SELECT FOR UPDATE locking primitive that prevents the check-then-deduct race.
"""
import threading
import uuid

import pytest
from django.test import Client

from apps.merchants.models import BankAccount, Merchant
from apps.payouts.models import LedgerEntry, Payout


@pytest.mark.django_db(transaction=True)
def test_concurrent_payout_requests_exactly_one_succeeds(funded_merchant, bank_account):
    """
    Two goroutine-equivalent threads hit POST /api/v1/payouts/ simultaneously,
    each requesting 6,000 paise on a 10,000 paise balance.

    Expected outcome: exactly 1 × HTTP 201, exactly 1 × HTTP 402.
    No overdraft. One Payout record in the database.
    """
    results: list[int] = []
    lock = threading.Lock()

    def request_payout(idempotency_key: str) -> None:
        client = Client()
        response = client.post(
            "/api/v1/payouts/",
            data={"amount_paise": 6_000, "bank_account_id": bank_account.pk},
            content_type="application/json",
            HTTP_X_MERCHANT_ID=str(funded_merchant.pk),
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        with lock:
            results.append(response.status_code)

    threads = [
        threading.Thread(target=request_payout, args=(str(uuid.uuid4()),)),
        threading.Thread(target=request_payout, args=(str(uuid.uuid4()),)),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = results.count(201)
    rejections = results.count(402)

    assert successes == 1, (
        f"Expected exactly 1 success, got {successes}. "
        f"Full results: {results}. "
        f"This indicates a race condition in balance check/deduct."
    )
    assert rejections == 1, (
        f"Expected exactly 1 rejection, got {rejections}. "
        f"Full results: {results}."
    )

    # Database-level assertion: only one payout record was created
    payout_count = Payout.objects.filter(merchant=funded_merchant).count()
    assert payout_count == 1, (
        f"Expected 1 payout in DB, found {payout_count}. "
        f"This means both requests slipped through the balance check."
    )


@pytest.mark.django_db(transaction=True)
def test_insufficient_balance_rejected_immediately(merchant, bank_account):
    """A payout exceeding total balance is rejected with 402, no payout created."""
    LedgerEntry.objects.create(
        merchant=merchant,
        entry_type=LedgerEntry.CREDIT,
        amount_paise=5_000,
        description="Seed 5000 paise",
    )

    client = Client()
    response = client.post(
        "/api/v1/payouts/",
        data={"amount_paise": 6_000, "bank_account_id": bank_account.pk},
        content_type="application/json",
        HTTP_X_MERCHANT_ID=str(merchant.pk),
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )

    assert response.status_code == 402
    assert Payout.objects.filter(merchant=merchant).count() == 0


@pytest.mark.django_db(transaction=True)
def test_held_balance_reduces_available_for_concurrent_request(merchant, bank_account):
    """
    After one payout is in PENDING state (funds held), a second request
    for the remaining balance cannot overdraw even if the first hasn't settled.
    """
    LedgerEntry.objects.create(
        merchant=merchant,
        entry_type=LedgerEntry.CREDIT,
        amount_paise=10_000,
        description="Seed 10000 paise",
    )
    # First payout takes 6000, leaving 4000 available
    Payout.objects.create(
        merchant=merchant,
        bank_account=bank_account,
        amount_paise=6_000,
        status=Payout.PENDING,
        idempotency_key=uuid.uuid4(),
    )

    client = Client()
    # Attempt 5000 paise — should fail because only 4000 is available
    response = client.post(
        "/api/v1/payouts/",
        data={"amount_paise": 5_000, "bank_account_id": bank_account.pk},
        content_type="application/json",
        HTTP_X_MERCHANT_ID=str(merchant.pk),
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )

    assert response.status_code == 402
    data = response.json()
    assert data["available_paise"] == 4_000
