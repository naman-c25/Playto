from rest_framework import serializers
from .models import BankAccount, Merchant


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = [
            "id",
            "account_holder_name",
            "account_number",
            "ifsc_code",
            "bank_name",
            "is_primary",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class MerchantSerializer(serializers.ModelSerializer):
    bank_accounts = BankAccountSerializer(many=True, read_only=True)

    class Meta:
        model = Merchant
        fields = ["id", "name", "email", "bank_accounts", "created_at"]
        read_only_fields = ["id", "created_at"]
