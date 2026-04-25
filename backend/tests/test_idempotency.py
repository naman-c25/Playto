"""
Idempotency tests: same Idempotency-Key header returns identical response.

The guarantee: a client that retries a failed network request (with the same key)
must never create a duplicate payout. The response must be byte-for-byte identical.

Keys are scoped per merchant: the same UUID used by two different merchants
creates two independent records and two independent payouts.
"""
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone

from apps.merchants.models import BankAccount, Merchant
from apps.payouts.models import IdempotencyKey, LedgerEntry, Payout


def _post_payout(merchant, bank_account, amount_paise, idempotency_key):
    client = Client()
    return client.post(
        "/api/v1/payouts/",
        data={"amount_paise": amount_paise, "bank_account_id": bank_account.pk},
        content_type="application/json",
        HTTP_X_MERCHANT_ID=str(merchant.pk),
        HTTP_IDEMPOTENCY_KEY=str(idempotency_key),
    )


@pytest.mark.django_db(transaction=True)
def test_same_idempotency_key_returns_same_response(funded_merchant, bank_account):
    """
    Two requests with the same key return identical status code and payout ID.
    Only one Payout record is created.
    """
    key = uuid.uuid4()

    r1 = _post_payout(funded_merchant, bank_account, 3_000, key)
    r2 = _post_payout(funded_merchant, bank_account, 3_000, key)

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"], "Replayed response must reference the same payout"

    assert Payout.objects.filter(merchant=funded_merchant).count() == 1, (
        "Idempotency violation: duplicate payout was created"
    )


@pytest.mark.django_db(transaction=True)
def test_different_keys_create_independent_payouts(funded_merchant, bank_account):
    """Two distinct keys produce two distinct payouts."""
    r1 = _post_payout(funded_merchant, bank_account, 3_000, uuid.uuid4())
    r2 = _post_payout(funded_merchant, bank_account, 3_000, uuid.uuid4())

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]
    assert Payout.objects.filter(merchant=funded_merchant).count() == 2


@pytest.mark.django_db(transaction=True)
def test_idempotency_key_scoped_to_merchant(funded_merchant, bank_account):
    """
    The same UUID used by two different merchants creates two separate payouts.
    Keys are (merchant_id, key) tuples, not just keys.
    """
    merchant2 = Merchant.objects.create(name="Merchant Two", email="two@example.com")
    bank2 = BankAccount.objects.create(
        merchant=merchant2,
        account_holder_name="Merchant Two",
        account_number="999888777666",
        ifsc_code="ICIC0001234",
        bank_name="ICICI Bank",
        is_primary=True,
    )
    LedgerEntry.objects.create(
        merchant=merchant2,
        entry_type=LedgerEntry.CREDIT,
        amount_paise=10_000,
        description="Seed",
    )

    shared_key = uuid.uuid4()

    r1 = _post_payout(funded_merchant, bank_account, 3_000, shared_key)
    r2 = _post_payout(merchant2, bank2, 3_000, shared_key)

    assert r1.status_code == 201
    assert r2.status_code == 201
    # Same key, different merchants → different payouts
    assert r1.json()["id"] != r2.json()["id"]


@pytest.mark.django_db(transaction=True)
def test_expired_idempotency_key_is_treated_as_fresh(funded_merchant, bank_account):
    """
    A key that has passed its 24-hour TTL is not replayed.
    The second request using the same key string is treated as a new request.
    """
    key = uuid.uuid4()

    # Plant an expired record in the DB directly
    IdempotencyKey.objects.create(
        merchant=funded_merchant,
        key=key,
        request_body={"amount_paise": 3_000, "bank_account_id": bank_account.pk},
        response_body={"id": 999, "status": "pending"},
        response_status=201,
        expires_at=timezone.now() - timedelta(hours=1),  # already expired
    )

    # This request should NOT get the cached response (key is expired)
    r = _post_payout(funded_merchant, bank_account, 3_000, key)

    # Should create a fresh payout, not replay the expired one
    assert r.status_code == 201
    assert r.json()["id"] != 999


@pytest.mark.django_db(transaction=True)
def test_missing_idempotency_key_header_returns_400(funded_merchant):
    """Omitting the Idempotency-Key header is a client error."""
    client = Client()
    response = client.post(
        "/api/v1/payouts/",
        data={"amount_paise": 1_000, "bank_account_id": 1},
        content_type="application/json",
        HTTP_X_MERCHANT_ID=str(funded_merchant.pk),
        # No HTTP_IDEMPOTENCY_KEY
    )
    assert response.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_invalid_idempotency_key_format_returns_400(funded_merchant):
    """A non-UUID idempotency key is rejected."""
    client = Client()
    response = client.post(
        "/api/v1/payouts/",
        data={"amount_paise": 1_000, "bank_account_id": 1},
        content_type="application/json",
        HTTP_X_MERCHANT_ID=str(funded_merchant.pk),
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )
    assert response.status_code == 400
