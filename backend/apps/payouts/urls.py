from django.urls import path
from .views import LedgerListView, PayoutCreateView, PayoutDetailView, PayoutListView

urlpatterns = [
    # Payout creation — the core API endpoint
    path("payouts/", PayoutCreateView.as_view(), name="payout-create"),
    path("payouts/<int:payout_id>/", PayoutDetailView.as_view(), name="payout-detail"),

    # Per-merchant resources
    path("merchants/<int:merchant_id>/payouts/", PayoutListView.as_view(), name="merchant-payout-list"),
    path("merchants/<int:merchant_id>/ledger/", LedgerListView.as_view(), name="merchant-ledger-list"),
]
