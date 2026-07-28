from django.urls import path
from . import webhooks

urlpatterns = [
    path('webhook/', webhooks.flutterwave_webhook, name='flutterwave_webhook'),
]
