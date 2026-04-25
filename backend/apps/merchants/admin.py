from django.contrib import admin
from .models import BankAccount, Merchant


class BankAccountInline(admin.TabularInline):
    model = BankAccount
    extra = 0
    readonly_fields = ["created_at"]


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "email", "created_at"]
    search_fields = ["name", "email"]
    readonly_fields = ["secret_token", "created_at", "updated_at"]
    inlines = [BankAccountInline]


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ["id", "merchant", "account_holder_name", "bank_name", "ifsc_code", "is_primary"]
    list_filter = ["is_primary", "bank_name"]
    search_fields = ["merchant__name", "account_holder_name", "ifsc_code"]
