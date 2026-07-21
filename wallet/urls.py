from django.urls import path
from . import views, webhooks

urlpatterns = [
    path('top-up/', views.top_up_with_voucher, name='wallet_top_up'),
    path('transfer/<int:group_id>/', views.transfer_to_group, name='wallet_transfer_group'),
    path('p2p-transfer/', views.send_p2p_money, name='wallet_p2p_transfer'),
    path('balance/', views.get_wallet_balance_snippet, name='wallet_balance'),
    path('history/', views.transaction_history, name='wallet_history'),
    path('history/group/<int:group_id>/', views.group_transaction_history, name='group_wallet_history'),
    path('webhook/', webhooks.flutterwave_webhook, name='flutterwave_webhook'),
]
