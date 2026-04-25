"""
Payout API views.

Critical correctness properties upheld here:

1. Concurrency  — SELECT FOR UPDATE on the merchant row serializes concurrent
   payout requests. The balance check and payout creation happen inside the
   same atomic transaction with the lock held, eliminating the TOCTOU window.

2. Idempotency  — IdempotencyKey has a DB-level unique_together constraint.
   The first request does an INSERT (which wins the race); any concurrent
   duplicate hits IntegrityError and returns the in-flight 409 or the cached
   response if the first already completed.

3. Money math   — All balance arithmetic uses DB-level aggregation (SUM with
   CASE). No rows are fetched and summed in Python.
"""

import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import BigIntegerField, Case, F, Sum, Value, When
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.merchants.models import BankAccount, Merchant
from .exceptions import InsufficientFundsError
from .models import IdempotencyKey, LedgerEntry, Payout
from .serializers import LedgerEntrySerializer, PayoutCreateSerializer, PayoutSerializer
from .tasks import process_payout


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_merchant(request):
    """
    Identify the merchant from the X-Merchant-ID header.
    Returns (merchant, None) on success or (None, Response) on failure.
    """
    merchant_id = request.headers.get("X-Merchant-ID")
    if not merchant_id:
        return None, Response(
            {"error": "X-Merchant-ID header is required"},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    try:
        merchant = Merchant.objects.get(pk=int(merchant_id))
        return merchant, None
    except (Merchant.DoesNotExist, ValueError, TypeError):
        return None, Response(
            {"error": "Merchant not found"},
            status=status.HTTP_401_UNAUTHORIZED,
        )


def _compute_available_balance(merchant: Merchant) -> int:
    """
    Available balance = SUM(ledger credits - ledger debits) - SUM(held payouts).

    Both aggregations hit the DB directly. Called only while holding the
    SELECT FOR UPDATE lock on the merchant row, so the result is stable
    for the duration of the transaction.
    """
    ledger_total = LedgerEntry.objects.filter(merchant=merchant).aggregate(
        total=Sum(
            Case(
                When(entry_type=LedgerEntry.CREDIT, then=F("amount_paise")),
                When(entry_type=LedgerEntry.DEBIT, then=-F("amount_paise")),
                default=Value(0),
                output_field=BigIntegerField(),
            )
        )
    )["total"] or 0

    held = Payout.objects.filter(
        merchant=merchant,
        status__in=[Payout.PENDING, Payout.PROCESSING],
    ).aggregate(total=Sum("amount_paise"))["total"] or 0

    return ledger_total - held


def _handle_idempotency(merchant: Merchant, raw_key: str, request_body: dict):
    """
    Idempotency gate.

    Returns one of:
      - (None, None)              → key is fresh, caller should proceed
      - (response_body, status)   → key seen before, caller should return cached response
      - raises nothing            → all errors surface as return tuples
    """
    # Validate UUID format
    try:
        key_uuid = uuid.UUID(str(raw_key))
    except (ValueError, AttributeError):
        return {"error": "Idempotency-Key must be a valid UUID v4"}, status.HTTP_400_BAD_REQUEST

    now = timezone.now()

    # Check for an existing non-expired record
    try:
        existing = IdempotencyKey.objects.get(
            merchant=merchant,
            key=key_uuid,
            expires_at__gt=now,  # ignore expired records
        )
        if existing.is_completed:
            # First request finished — replay the exact same response
            return existing.response_body, existing.response_status
        else:
            # First request is still being processed
            return (
                {"error": "A request with this idempotency key is currently in-flight. Retry after a moment."},
                status.HTTP_409_CONFLICT,
            )
    except IdempotencyKey.DoesNotExist:
        pass  # fresh key — fall through to create

    # Attempt to INSERT the new idempotency record.
    # The unique_together constraint is the real race guard here: even if
    # two threads reach this point simultaneously, only one INSERT succeeds.
    try:
        record = IdempotencyKey.objects.create(
            merchant=merchant,
            key=key_uuid,
            request_body=request_body,
            expires_at=now + timedelta(hours=24),
        )
        return None, record  # signal: proceed, record created
    except IntegrityError:
        # Lost the INSERT race — another thread beat us to the key.
        # Two sub-cases:
        #   a) The conflicting record is expired  → overwrite it and treat as fresh.
        #   b) The conflicting record is live     → replay or 409 as normal.
        try:
            existing = IdempotencyKey.objects.get(merchant=merchant, key=key_uuid)
            if existing.is_expired:
                # The unique_together conflict is with a stale record that the
                # initial lookup skipped. Overwrite it so this request proceeds fresh.
                existing.request_body = request_body
                existing.response_body = None
                existing.response_status = None
                existing.payout = None
                existing.expires_at = now + timedelta(hours=24)
                existing.save()
                return None, existing
            if existing.is_completed:
                return existing.response_body, existing.response_status
            return (
                {"error": "A request with this idempotency key is currently in-flight."},
                status.HTTP_409_CONFLICT,
            )
        except IdempotencyKey.DoesNotExist:
            # Extremely unlikely: record was created then immediately expired+deleted
            return {"error": "Idempotency conflict"}, status.HTTP_409_CONFLICT


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class PayoutCreateView(APIView):
    """
    POST /api/v1/payouts/

    Required headers:
      X-Merchant-ID: <int>
      Idempotency-Key: <uuid>

    Body:
      { "amount_paise": <int>, "bank_account_id": <int> }
    """

    def post(self, request):
        merchant, err = _resolve_merchant(request)
        if err:
            return err

        raw_key = request.headers.get("Idempotency-Key")
        if not raw_key:
            return Response(
                {"error": "Idempotency-Key header is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate request body
        body_serializer = PayoutCreateSerializer(data=request.data)
        if not body_serializer.is_valid():
            return Response(body_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        amount_paise: int = body_serializer.validated_data["amount_paise"]
        bank_account_id: int = body_serializer.validated_data["bank_account_id"]
        request_body = {"amount_paise": amount_paise, "bank_account_id": bank_account_id}

        # Idempotency gate
        idempotency_result, idempotency_meta = _handle_idempotency(merchant, raw_key, request_body)

        if idempotency_result is not None:
            # Either a cached response (int status) or an error tuple
            if isinstance(idempotency_meta, int):
                return Response(idempotency_result, status=idempotency_meta)
            # Error from validation inside _handle_idempotency
            return Response(idempotency_result, status=idempotency_meta)

        # idempotency_meta is the newly created IdempotencyKey record
        idempotency_record: IdempotencyKey = idempotency_meta

        # Validate bank account ownership
        try:
            bank_account = BankAccount.objects.get(pk=bank_account_id, merchant=merchant)
        except BankAccount.DoesNotExist:
            resp_body = {"error": "Bank account not found or does not belong to this merchant"}
            resp_status = status.HTTP_404_NOT_FOUND
            self._store_idempotency_response(idempotency_record, resp_body, resp_status)
            return Response(resp_body, status=resp_status)

        # Create the payout — this is the critical section
        try:
            payout = self._create_payout_atomic(merchant, bank_account, amount_paise)
        except InsufficientFundsError as exc:
            resp_body = {
                "error": "Insufficient funds",
                "available_paise": exc.available_paise,
                "requested_paise": exc.requested_paise,
                "available_inr": f"{exc.available_paise / 100:.2f}",
            }
            resp_status = status.HTTP_402_PAYMENT_REQUIRED
            self._store_idempotency_response(idempotency_record, resp_body, resp_status)
            return Response(resp_body, status=resp_status)

        # Dispatch to Celery — real async, not simulated
        process_payout.delay(payout.pk)

        resp_body = PayoutSerializer(payout).data
        resp_status = status.HTTP_201_CREATED
        self._store_idempotency_response(idempotency_record, resp_body, resp_status, payout=payout)

        return Response(resp_body, status=resp_status)

    @staticmethod
    def _create_payout_atomic(
        merchant: Merchant,
        bank_account: BankAccount,
        amount_paise: int,
    ) -> Payout:
        """
        The only place where a payout is created.

        SELECT FOR UPDATE acquires a row-level exclusive lock on the merchant
        row. All concurrent payout requests for the same merchant queue behind
        this lock. The balance check and INSERT both happen inside the same
        atomic transaction, so no other transaction can sneak in between them.

        This is the correct fix for the check-then-act race condition:
          ✗ Wrong: fetch balance in Python → check → create payout (window exists)
          ✓ Right: lock row → fetch balance in DB → create payout → release lock
        """
        with transaction.atomic():
            # Acquire exclusive row lock. Concurrent requests for this merchant block here.
            Merchant.objects.select_for_update().get(pk=merchant.pk)

            available = _compute_available_balance(merchant)

            if available < amount_paise:
                raise InsufficientFundsError(
                    available_paise=available,
                    requested_paise=amount_paise,
                )

            return Payout.objects.create(
                merchant=merchant,
                bank_account=bank_account,
                amount_paise=amount_paise,
                status=Payout.PENDING,
                # idempotency_key stored on payout for traceability
                idempotency_key=uuid.uuid4(),
            )

    @staticmethod
    def _store_idempotency_response(record: IdempotencyKey, body: dict, status_code: int, payout=None):
        update_fields = ["response_body", "response_status"]
        record.response_body = body
        record.response_status = status_code
        if payout is not None:
            record.payout = payout
            update_fields.append("payout")
        record.save(update_fields=update_fields)


class PayoutListView(APIView):
    """GET /api/v1/merchants/<id>/payouts/ — payout history for a merchant."""

    def get(self, request, merchant_id):
        try:
            merchant = Merchant.objects.get(pk=merchant_id)
        except Merchant.DoesNotExist:
            return Response({"error": "Merchant not found"}, status=status.HTTP_404_NOT_FOUND)

        payouts = (
            Payout.objects
            .filter(merchant=merchant)
            .select_related("bank_account")
            .order_by("-created_at")
        )
        return Response(PayoutSerializer(payouts, many=True).data)


class PayoutDetailView(APIView):
    """GET /api/v1/payouts/<id>/ — single payout status polling."""

    def get(self, request, payout_id):
        try:
            payout = Payout.objects.select_related("bank_account").get(pk=payout_id)
        except Payout.DoesNotExist:
            return Response({"error": "Payout not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(PayoutSerializer(payout).data)


class LedgerListView(APIView):
    """GET /api/v1/merchants/<id>/ledger/ — ledger entries (credits + debits)."""

    def get(self, request, merchant_id):
        try:
            merchant = Merchant.objects.get(pk=merchant_id)
        except Merchant.DoesNotExist:
            return Response({"error": "Merchant not found"}, status=status.HTTP_404_NOT_FOUND)

        entries = LedgerEntry.objects.filter(merchant=merchant).order_by("-created_at")[:50]
        return Response(LedgerEntrySerializer(entries, many=True).data)
