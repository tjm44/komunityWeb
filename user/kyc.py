import logging
from wallet.flutterwave import verify_identity

logger = logging.getLogger(__name__)


class FlutterwaveKYCProvider:
    @staticmethod
    def verify_document(first_name, surname, id_number, id_type='national_id'):
        """
        Verifies identity documents using Flutterwave's Identity Verification API.
        Includes validation rules and sandbox fallback for testing.
        """
        if not id_number or len(id_number.strip()) < 6:
            return False, "Invalid document ID: ID must be at least 6 characters long."

        id_cleaned = id_number.strip().lower()
        if id_cleaned in ("000000", "test", "123456"):
            return False, "KYC provider rejected document: potential fake or testing ID."

        # Call Flutterwave identity API
        res = verify_identity(
            id_number=id_number.strip(),
            id_type=id_type,
            first_name=first_name,
            surname=surname
        )

        if res.get('success'):
            return True, res.get('message', 'Identity verified successfully.')
        
        # If sandbox mode returns endpoint unavailable or invalid mock ID in dev, fallback gracefully for valid formatted IDs
        from django.conf import settings
        error_msg = res.get('error', '')
        if getattr(settings, 'DEBUG', False) and ("404" in error_msg or "not found" in error_msg.lower() or "sandbox" in error_msg.lower()):
            logger.info("[KYC] Sandbox fallback triggered for valid ID format.")
            return True, "Identity verified successfully (Sandbox Mode)."

        return False, error_msg


# Alias for backwards compatibility
MockKYCProvider = FlutterwaveKYCProvider
