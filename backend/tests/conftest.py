"""
Shared pytest fixtures for the payout engine test suite.
"""
import pytest
from apps.merchants.models import BankAccount, Merchant
from apps.payouts.models import LedgerEntry


@pytest.fixture
def merchant(db):
    """A fresh merchant with no balance or payouts."""
    return Merchant.objects.create(
        name="Test Merchant",
        email="test@merchant.com",
    )


@pytest.fixture
def bank_account(merchant):
    """A primary bank account for the test merchant."""
    return BankAccount.objects.create(
        merchant=merchant,
        account_holder_name="Test Merchant",
        account_number="123456789012",
        ifsc_code="HDFC0001234",
        bank_name="HDFC Bank",
        is_primary=True,
    )


@pytest.fixture
def funded_merchant(merchant):
    """
    A merchant pre-credited with 10,000 paise (₹100).
    Used in tests that need a positive balance to work with.
    """
    LedgerEntry.objects.create(
        merchant=merchant,
        entry_type=LedgerEntry.CREDIT,
        amount_paise=10_000,
        description="Seed credit for testing",
    )
    return merchant
