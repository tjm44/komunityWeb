"""
wallet/encryption.py
====================
Fernet symmetric encryption for sensitive financial fields stored in the
`withdrawal_metadata` JSON column (bank account numbers, mobile-money
phone numbers, etc.).

The FERNET_KEY environment variable must be a URL-safe base64-encoded
32-byte key.  Generate one with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Then add it to your .env (dev) and to the Render / Railway secret manager
(production).  The same key must be used for the lifetime of the data —
losing it means losing the ability to decrypt existing records.
"""

import logging
from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-loaded cipher — only imported if the feature is actually used so the
# app still starts even if cryptography is somehow missing from the venv.
# ---------------------------------------------------------------------------
_cipher = None


def _get_cipher():
    global _cipher
    if _cipher is not None:
        return _cipher

    from cryptography.fernet import Fernet, InvalidToken  # noqa: F401

    key = getattr(settings, 'FERNET_KEY', None)
    if not key:
        raise RuntimeError(
            "FERNET_KEY is not configured. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
            "and add it to your .env file."
        )
    _cipher = Fernet(key.encode() if isinstance(key, str) else key)
    return _cipher


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------

def encrypt_field(plaintext: str) -> str:
    """Encrypt *plaintext* and return a URL-safe base64 ciphertext string."""
    cipher = _get_cipher()
    return cipher.encrypt(plaintext.encode('utf-8')).decode('utf-8')


def decrypt_field(ciphertext: str) -> str:
    """Decrypt a ciphertext produced by :func:`encrypt_field`."""
    from cryptography.fernet import InvalidToken
    cipher = _get_cipher()
    try:
        return cipher.decrypt(ciphertext.encode('utf-8')).decode('utf-8')
    except (InvalidToken, Exception) as exc:
        logger.error("Failed to decrypt field: %s", exc)
        # Return a safe placeholder rather than crashing the response
        return "[decryption error]"


def is_encrypted(value: str) -> bool:
    """
    Heuristic: Fernet tokens always start with 'gAAAAA' (version byte 0x80
    followed by the timestamp, encoded in URL-safe base64).
    """
    return isinstance(value, str) and value.startswith('gAAAAA')


# ---------------------------------------------------------------------------
# Keys that must be encrypted inside withdrawal_metadata
# ---------------------------------------------------------------------------
SENSITIVE_METADATA_KEYS = ('account_number', 'phone_number')


def encrypt_metadata(metadata: dict) -> dict:
    """
    Return a copy of *metadata* with :data:`SENSITIVE_METADATA_KEYS` encrypted.
    Values that are already encrypted (``gAAAAA…``) are left untouched so the
    helper is idempotent.
    """
    if not metadata:
        return metadata
    result = dict(metadata)
    for key in SENSITIVE_METADATA_KEYS:
        value = result.get(key)
        if value and not is_encrypted(str(value)):
            result[key] = encrypt_field(str(value))
    return result


def decrypt_metadata(metadata: dict) -> dict:
    """
    Return a copy of *metadata* with :data:`SENSITIVE_METADATA_KEYS` decrypted.
    Non-encrypted values (plain strings) are returned as-is so the helper is
    safe to call on old records that pre-date encryption.
    """
    if not metadata:
        return metadata
    result = dict(metadata)
    for key in SENSITIVE_METADATA_KEYS:
        value = result.get(key)
        if value and is_encrypted(str(value)):
            result[key] = decrypt_field(str(value))
    return result


def mask_metadata(metadata: dict) -> dict:
    """
    Return a copy of *metadata* with :data:`SENSITIVE_METADATA_KEYS` masked
    to show only the last 4 characters.  Decrypts first if the value is
    encrypted.  Intended for use in API serializers.
    """
    if not metadata:
        return metadata
    result = dict(metadata)
    for key in SENSITIVE_METADATA_KEYS:
        value = result.get(key)
        if not value:
            continue
        # Decrypt if needed so we can mask the real value
        plain = decrypt_field(str(value)) if is_encrypted(str(value)) else str(value)
        if len(plain) > 4:
            result[key] = f"****{plain[-4:]}"
        else:
            result[key] = "****"
    return result
