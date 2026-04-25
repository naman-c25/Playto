from rest_framework import serializers
from apps.merchants.serializers import BankAccountSerializer
from .models import LedgerEntry, Payout


class LedgerEntrySerializer(serializers.ModelSerializer):
    amount_inr = serializers.SerializerMethodField()
    usd_amount = serializers.SerializerMethodField()
    exchange_rate_display = serializers.SerializerMethodField()

    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "entry_type",
            "amount_paise",
            "amount_inr",
            # USD origin — present on customer-payment credits, null on debits
            "usd_cents",
            "usd_amount",
            "exchange_rate",
            "exchange_rate_display",
            "description",
            "payout_id",
            "created_at",
        ]
        read_only_fields = fields

    def get_amount_inr(self, obj) -> str:
        return f"{obj.amount_paise / 100:.2f}"

    def get_usd_amount(self, obj) -> str | None:
        if obj.usd_cents is None:
            return None
        return f"{obj.usd_cents / 100:.2f}"

    def get_exchange_rate_display(self, obj) -> str | None:
        if obj.exchange_rate is None:
            return None
        return f"{float(obj.exchange_rate):.2f}"


class PayoutSerializer(serializers.ModelSerializer):
    bank_account = BankAccountSerializer(read_only=True)
    amount_inr = serializers.SerializerMethodField()

    class Meta:
        model = Payout
        fields = [
            "id",
            "merchant_id",
            "bank_account",
            "amount_paise",
            "amount_inr",
            "status",
            "idempotency_key",
            "attempt_count",
            "processing_started_at",
            "completed_at",
            "failed_at",
            "failure_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_amount_inr(self, obj) -> str:
        return f"{obj.amount_paise / 100:.2f}"


class PayoutCreateSerializer(serializers.Serializer):
    amount_paise = serializers.IntegerField(min_value=1)
    bank_account_id = serializers.IntegerField()

    def validate_amount_paise(self, value):
        # Minimum payout: ₹1 (100 paise)
        if value < 100:
            raise serializers.ValidationError("Minimum payout amount is 100 paise (₹1).")
        return value
