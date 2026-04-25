import uuid
from django.db import models


class Merchant(models.Model):
    """
    Represents an Indian agency or freelancer on the Playto Pay platform.

    Authentication is simplified for this challenge: each merchant has a
    `secret_token` used as a bearer token in API requests. A production system
    would use OAuth2 or JWT with refresh tokens.
    """

    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    secret_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"


class BankAccount(models.Model):
    """
    Indian bank account (IFSC-routed) where payout funds are settled.

    account_number is stored in plaintext for this demo. Production would
    encrypt it at rest using field-level encryption (e.g., django-fernet-fields).
    """

    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.CASCADE,
        related_name="bank_accounts",
    )
    account_holder_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=20)
    ifsc_code = models.CharField(max_length=11)
    bank_name = models.CharField(max_length=255)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "created_at"]

    def __str__(self) -> str:
        return f"{self.account_holder_name} — {self.bank_name} {self.ifsc_code}"
