from django.contrib import admin
from django.utils.html import format_html
from .models import IdempotencyKey, LedgerEntry, Payout


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ["id", "merchant", "entry_type", "amount_paise", "amount_inr", "description", "created_at"]
    list_filter = ["entry_type", "merchant"]
    search_fields = ["merchant__name", "description"]
    readonly_fields = ["created_at"]

    def amount_inr(self, obj):
        return f"₹{obj.amount_paise / 100:.2f}"
    amount_inr.short_description = "Amount (INR)"


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = [
        "id", "merchant", "amount_paise", "amount_inr", "status_badge",
        "attempt_count", "created_at", "updated_at",
    ]
    list_filter = ["status", "merchant"]
    search_fields = ["merchant__name", "idempotency_key"]
    readonly_fields = [
        "idempotency_key", "attempt_count", "processing_started_at",
        "completed_at", "failed_at", "created_at", "updated_at",
    ]

    STATUS_COLORS = {
        "pending": "#f59e0b",
        "processing": "#3b82f6",
        "completed": "#10b981",
        "failed": "#ef4444",
    }

    def amount_inr(self, obj):
        return f"₹{obj.amount_paise / 100:.2f}"
    amount_inr.short_description = "Amount (INR)"

    def status_badge(self, obj):
        color = self.STATUS_COLORS.get(obj.status, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;">{}</span>',
            color,
            obj.status.upper(),
        )
    status_badge.short_description = "Status"


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ["id", "merchant", "key", "response_status", "created_at", "expires_at"]
    list_filter = ["merchant", "response_status"]
    search_fields = ["merchant__name", "key"]
    readonly_fields = ["key", "merchant", "request_body", "response_body", "response_status", "created_at"]
