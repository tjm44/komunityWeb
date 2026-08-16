import logging
try:
    from exponent_server_sdk import (
        PushClient, PushMessage, DeviceNotRegisteredError,
        PushServerError, PushTicketError
    )
except ImportError:
    PushClient = PushMessage = DeviceNotRegisteredError = PushServerError = PushTicketError = None
    print("Warning: exponent_server_sdk not found or failed to import. Push notifications will be disabled.")
from django.conf import settings
from .models import DeviceToken, Notification

logger = logging.getLogger(__name__)

def send_push_notification(user, title, message, data=None, notification_type=None):
    """
    Send push notification to a user's devices and store it in DB.
    Deactivates device tokens if Expo returns DeviceNotRegistered.
    """
    if data is None:
        data = {}

    # Store notification in DB
    Notification.objects.create(
        recipient=user,
        title=title,
        message=message,
        data=data,
        notification_type=notification_type
    )

    # Get active tokens
    tokens = list(DeviceToken.objects.filter(user=user, is_active=True).values_list('token', flat=True))
    
    if not tokens:
        return

    if not PushClient:
        logger.info("PushClient not available. Skipping notification.")
        return

    try:
        messages = [
            PushMessage(to=token, title=title, body=message, data=data)
            for token in tokens
        ]
        responses = PushClient().publish_multiple(messages)

        for token, response_ticket in zip(tokens, responses):
            try:
                response_ticket.validate_response()
            except Exception as exc:
                exc_str = str(exc)
                if (DeviceNotRegisteredError and isinstance(exc, DeviceNotRegisteredError)) or "DeviceNotRegistered" in exc_str:
                    logger.info(f"Deactivating unregistered device token: {token}")
                    DeviceToken.objects.filter(token=token).update(is_active=False)
                else:
                    logger.warning(f"Push notification ticket error for token {token}: {exc}")

    except Exception as exc:
        logger.error(f"Error sending push notification batch: {exc}")

