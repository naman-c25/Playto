from django.urls import path
from .views import MerchantListView, MerchantDetailView, MerchantBalanceView

urlpatterns = [
    path("merchants/", MerchantListView.as_view(), name="merchant-list"),
    path("merchants/<int:merchant_id>/", MerchantDetailView.as_view(), name="merchant-detail"),
    path("merchants/<int:merchant_id>/balance/", MerchantBalanceView.as_view(), name="merchant-balance"),
]
