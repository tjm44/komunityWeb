import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

def send_otp_sms(phone: str, otp: str) -> bool:
    """
    Sends an SMS containing the OTP to the specified phone number.
    Uses BulkSMS service if credentials are configured in settings;
    otherwise logs the OTP to console/logger for development.
    """
    sms_username = getattr(settings, 'BULK_SMS_USERNAME', None)
    sms_password = getattr(settings, 'BULK_SMS_PASSWORD', None)
    sms_token = getattr(settings, 'BULK_SMS_TOKEN', None)
    message = f"Your Komunity verification code is: {otp}. Valid for 10 minutes."

    # Always log OTP in console/logger for local dev/testing
    print(f"\n==========================================")
    print(f"[DEV SMS ENGINE] OTP for {phone}: {otp}")
    print(f"==========================================\n")
    logger.info(f"[SMS OTP] Phone: {phone} | OTP: {otp}")

    # If BulkSMS credentials are configured, execute HTTP request
    if sms_token or (sms_username and sms_password):
        try:
            url = "https://api.bulksms.com/v1/messages"
            headers = {
                "Content-Type": "application/json",
            }
            auth = None
            if sms_token:
                headers["Authorization"] = f"Bearer {sms_token}"
            else:
                auth = (sms_username, sms_password)

            payload = {
                "to": phone,
                "body": message
            }

            response = requests.post(url, json=payload, headers=headers, auth=auth, timeout=10)
            if response.status_code in (200, 201):
                logger.info(f"BulkSMS successfully dispatched to {phone}")
                return True
            else:
                logger.error(f"BulkSMS Response Error {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"BulkSMS Connection Error: {e}")

    return True
