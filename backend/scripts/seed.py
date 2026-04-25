"""
Seed script — populates the database with realistic demo data.

Run with:
    python manage.py shell < scripts/seed.py

Data model:
  - International customers pay merchants in USD.
  - At the time of payment, the USD amount is converted to INR at the
    prevailing exchange rate and credited to the merchant's ledger in paise.
  - Both the original USD amount and the rate used are stored on the
    LedgerEntry for full auditability.
  - Payouts are always in INR (paise) — merchants withdraw to Indian bank accounts.
"""
import random
import uuid
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.merchants.models import BankAccount, Merchant
from apps.payouts.models import LedgerEntry, Payout


# ---------------------------------------------------------------------------
# Simulated USD/INR exchange rates
# ---------------------------------------------------------------------------
# Production would fetch the live RBI reference rate or use a provider like
# Wise / Fixer.io. For this demo we use a realistic base rate with slight
# day-to-day variation to make historical entries look authentic.

_BASE_RATE_INR_PER_USD = Decimal("83.50")

def _get_exchange_rate(days_ago: int) -> Decimal:
    """
    Simulate historical USD/INR rates with ±1.5% daily variation.
    Older entries naturally have slightly different rates than recent ones.
    """
    seed_val = days_ago * 17 + 42           # deterministic per day
    random.seed(seed_val)
    variation = Decimal(str(random.uniform(-0.015, 0.015)))
    rate = _BASE_RATE_INR_PER_USD * (1 + variation)
    random.seed()                            # restore global randomness
    return rate.quantize(Decimal("0.0001"))


def _usd_to_paise(usd_cents: int, rate: Decimal) -> int:
    """
    Convert USD cents to INR paise using integer arithmetic.
    usd_cents * rate gives INR (since rate is INR/USD and we have cents not dollars,
    divide by 100 to get dollars, multiply by 100 for paise — they cancel out).

    Example: 50000 cents ($500.00) at 83.5000 INR/USD
        = 50000 * 83.5000 / 100 * 100 paise = 4_175_000 paise (₹41,750)
    """
    return int(usd_cents * rate)


def run():
    print("Seeding database...")

    # ------------------------------------------------------------------
    # Merchants + bank accounts
    # ------------------------------------------------------------------
    merchants_data = [
        {
            "name": "Arjun Sharma Design Studio",
            "email": "arjun@sharmadesign.in",
            "bank": {
                "account_holder_name": "Arjun Sharma",
                "account_number": "50100234567890",
                "ifsc_code": "HDFC0001234",
                "bank_name": "HDFC Bank",
            },
        },
        {
            "name": "Priya Nair Consulting",
            "email": "priya@nairhq.in",
            "bank": {
                "account_holder_name": "Priya Nair",
                "account_number": "919010056789012",
                "ifsc_code": "ICIC0005678",
                "bank_name": "ICICI Bank",
            },
        },
        {
            "name": "Devbridge Software LLP",
            "email": "finance@devbridge.io",
            "bank": {
                "account_holder_name": "Devbridge Software LLP",
                "account_number": "3914000123456789",
                "ifsc_code": "KKBK0001234",
                "bank_name": "Kotak Mahindra Bank",
            },
        },
    ]

    merchants = []
    for data in merchants_data:
        merchant, created = Merchant.objects.get_or_create(
            email=data["email"],
            defaults={"name": data["name"]},
        )
        if created:
            print(f"  Created merchant: {merchant.name}")
        else:
            print(f"  Merchant already exists: {merchant.name}")

        bank, _ = BankAccount.objects.get_or_create(
            merchant=merchant,
            ifsc_code=data["bank"]["ifsc_code"],
            defaults={**data["bank"], "is_primary": True},
        )
        merchants.append((merchant, bank))

    # ------------------------------------------------------------------
    # Credit history — international customer payments in USD, converted to INR
    # ------------------------------------------------------------------
    # Each entry stores the original USD cents, the exchange rate used, and
    # the converted INR paise amount. This mirrors a real cross-border payout
    # system where USD arrives from abroad and settles as INR.
    credit_scenarios = [
        # (description_template, min_usd_cents, max_usd_cents, count)
        ("Client payment — Invoice #{inv}", 30_000, 150_000, 5),   # $300–$1500
        ("Retainer fee — {month}", 80_000, 300_000, 2),            # $800–$3000
        ("Project milestone — Phase {phase}", 50_000, 200_000, 3), # $500–$2000
    ]

    now = timezone.now()

    for merchant, bank in merchants:
        if LedgerEntry.objects.filter(merchant=merchant, entry_type=LedgerEntry.CREDIT).exists():
            print(f"  Credits already seeded for {merchant.name}, skipping")
            continue

        print(f"  Seeding USD→INR credits for {merchant.name}")
        inv = random.randint(1001, 1999)
        for description_tmpl, min_cents, max_cents, count in credit_scenarios:
            for i in range(count):
                days_ago = random.randint(1, 30)
                created_at = now - timedelta(days=days_ago, hours=random.randint(0, 23))
                rate = _get_exchange_rate(days_ago)

                usd_cents = random.randint(min_cents, max_cents)
                amount_paise = _usd_to_paise(usd_cents, rate)

                description = description_tmpl.format(
                    inv=inv + i,
                    month=(now - timedelta(days=days_ago * 2)).strftime("%B %Y"),
                    phase=i + 1,
                )

                entry = LedgerEntry(
                    merchant=merchant,
                    entry_type=LedgerEntry.CREDIT,
                    amount_paise=amount_paise,
                    usd_cents=usd_cents,
                    exchange_rate=rate,
                    description=description,
                )
                entry.save()
                # Backdate the entry to simulate history over the past month
                LedgerEntry.objects.filter(pk=entry.pk).update(created_at=created_at)

    # ------------------------------------------------------------------
    # Historical payouts — completed and failed, to populate the UI table
    # ------------------------------------------------------------------
    for merchant, bank in merchants:
        if Payout.objects.filter(merchant=merchant).exists():
            print(f"  Payouts already seeded for {merchant.name}, skipping")
            continue

        print(f"  Seeding payout history for {merchant.name}")

        # Two completed payouts (INR to bank account)
        for i in range(2):
            amount_paise = random.randint(50_000, 200_000)  # ₹500–₹2000
            days_ago = random.randint(5, 25)
            payout = Payout.objects.create(
                merchant=merchant,
                bank_account=bank,
                amount_paise=amount_paise,
                status=Payout.COMPLETED,
                idempotency_key=uuid.uuid4(),
                attempt_count=1,
                processing_started_at=now - timedelta(days=days_ago, minutes=2),
                completed_at=now - timedelta(days=days_ago, minutes=1),
            )
            # Debit entry — no USD fields (payout is already in INR)
            LedgerEntry.objects.create(
                merchant=merchant,
                entry_type=LedgerEntry.DEBIT,
                amount_paise=amount_paise,
                payout=payout,
                description=f"Payout #{payout.pk} settled to bank account",
            )
            Payout.objects.filter(pk=payout.pk).update(
                created_at=now - timedelta(days=days_ago, minutes=5)
            )

        # One failed payout (funds released back, no debit entry)
        Payout.objects.create(
            merchant=merchant,
            bank_account=bank,
            amount_paise=random.randint(20_000, 80_000),
            status=Payout.FAILED,
            idempotency_key=uuid.uuid4(),
            attempt_count=3,
            processing_started_at=now - timedelta(days=3, minutes=2),
            failed_at=now - timedelta(days=3, minutes=1),
            failure_reason="Bank rejected the transfer (simulated failure)",
        )

    print("\nSeed complete.")
    print("\nCurrent USD/INR rate used for recent credits: ₹{:.2f}/$".format(_BASE_RATE_INR_PER_USD))
    print("\nMerchant IDs (use as X-Merchant-ID header):")
    for merchant, _ in merchants:
        merchant.refresh_from_db()
        print(f"  ID={merchant.pk}  {merchant.name}")


run()
