from django.db.models import BigIntegerField, Case, F, Sum, Value, When
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payouts.models import LedgerEntry, Payout
from .models import Merchant
from .serializers import MerchantSerializer


class MerchantListView(APIView):
    """List all merchants. Used by the frontend merchant selector."""

    def get(self, request):
        merchants = Merchant.objects.prefetch_related("bank_accounts").all()
        serializer = MerchantSerializer(merchants, many=True)
        return Response(serializer.data)


class MerchantDetailView(APIView):
    def get(self, request, merchant_id):
        try:
            merchant = Merchant.objects.prefetch_related("bank_accounts").get(pk=merchant_id)
        except Merchant.DoesNotExist:
            return Response({"error": "Merchant not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = MerchantSerializer(merchant)
        return Response(serializer.data)


class MerchantBalanceView(APIView):
    """
    Return balance breakdown for a merchant.

    Balance model:
      total_balance   = SUM(credit entries) − SUM(debit entries)
      held_balance    = SUM of pending + processing payout amounts
      available_balance = total_balance − held_balance

    All arithmetic happens in the database. No Python-level row summation.
    The invariant `total_balance == SUM(credits) − SUM(debits)` is always true
    because balance is never stored separately — it's always recomputed from the ledger.
    """

    def get(self, request, merchant_id):
        try:
            merchant = Merchant.objects.get(pk=merchant_id)
        except Merchant.DoesNotExist:
            return Response({"error": "Merchant not found"}, status=status.HTTP_404_NOT_FOUND)

        total_balance = self._compute_ledger_balance(merchant)
        held_balance = self._compute_held_balance(merchant)
        available_balance = total_balance - held_balance
        total_earned = self._compute_total_earned(merchant)

        return Response(
            {
                "merchant_id": merchant.id,
                "merchant_name": merchant.name,
                "total_balance_paise": total_balance,
                "held_balance_paise": held_balance,
                "available_balance_paise": available_balance,
                "total_earned_paise": total_earned,
                # Human-readable INR strings for the UI
                "total_balance_inr": f"{total_balance / 100:.2f}",
                "held_balance_inr": f"{held_balance / 100:.2f}",
                "available_balance_inr": f"{available_balance / 100:.2f}",
                "total_earned_inr": f"{total_earned / 100:.2f}",
            }
        )

    @staticmethod
    def _compute_ledger_balance(merchant: Merchant) -> int:
        """
        SUM(credits) − SUM(debits) using a single DB aggregation.
        COALESCE via `or 0` handles the case where there are no entries yet.
        """
        result = LedgerEntry.objects.filter(merchant=merchant).aggregate(
            total=Sum(
                Case(
                    When(entry_type=LedgerEntry.CREDIT, then=F("amount_paise")),
                    When(entry_type=LedgerEntry.DEBIT, then=-F("amount_paise")),
                    default=Value(0),
                    output_field=BigIntegerField(),
                )
            )
        )
        return result["total"] or 0

    @staticmethod
    def _compute_total_earned(merchant: Merchant) -> int:
        """
        Lifetime gross earnings — sum of all CREDIT entries only.
        Unlike total_balance, this does NOT decrease when the merchant withdraws.
        """
        result = LedgerEntry.objects.filter(
            merchant=merchant,
            entry_type=LedgerEntry.CREDIT,
        ).aggregate(total=Sum("amount_paise"))
        return result["total"] or 0

    @staticmethod
    def _compute_held_balance(merchant: Merchant) -> int:
        """
        Funds held by payouts in-flight (pending or processing).
        These are not yet debited from the ledger — they become a debit
        only on successful completion, or are released on failure.
        """
        result = Payout.objects.filter(
            merchant=merchant,
            status__in=[Payout.PENDING, Payout.PROCESSING],
        ).aggregate(total=Sum("amount_paise"))
        return result["total"] or 0
