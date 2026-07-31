import uuid
import base64
import logging
import random
import string
import requests
from django.conf import settings
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

FLW_SANDBOX_BASE_URL = "https://developersandbox-api.flutterwave.com"
FLW_TOKEN_URL = "https://idp.flutterwave.com/realms/flutterwave/protocol/openid-connect/token"


def get_access_token():
    """Fetch a transient OAuth 2.0 bearer token from Flutterwave IDP."""
    client_id = getattr(settings, 'FLW_CLIENT_ID', None)
    client_secret = getattr(settings, 'FLW_CLIENT_SECRET', None)
    if not client_id or not client_secret:
        raise ValueError("Flutterwave Client ID or Client Secret not configured in settings.")

    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'client_credentials'
    }
    response = requests.post(
        FLW_TOKEN_URL,
        data=payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        timeout=15
    )
    response.raise_for_status()
    token = response.json().get('access_token')
    if not token:
        raise ValueError("No access_token returned from Flutterwave IDP.")
    return token


def get_headers(scenario_key=None):
    """Build the auth headers, optionally including a sandbox scenario key."""
    token = get_access_token()
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'X-Trace-Id': f'komunity-{uuid.uuid4().hex[:12]}',
    }
    if scenario_key:
        headers['X-Scenario-Key'] = scenario_key
    return headers


def charge_voucher(voucher_pin, amount, email, phone_number, tx_ref):
    """
    Charges a voucher in the Flutterwave v4 sandbox.
    1. Creates/retrieves customer.
    2. Registers a sandbox payment method (mobile_money / GHS).
    3. Triggers simulated charge.
    """
    try:
        headers = get_headers()
        
        # 1. Create customer
        cust_url = f"{FLW_SANDBOX_BASE_URL}/customers"
        cust_payload = {
            "email": email,
            "name": {"first": "Komunity", "last": "User"},
            "phone": {
                "country_code": "233",
                "number": "100001001"
            }
        }
        cust_resp = requests.post(cust_url, json=cust_payload, headers=headers, timeout=15)
        cust_data = cust_resp.json()
        customer_id = (cust_data.get('data') or {}).get('id')
        
        if not customer_id:
            search_resp = requests.get(f"{cust_url}?email={email}", headers=headers, timeout=15)
            search_data = search_resp.json()
            items = search_data.get('data') or []
            if isinstance(items, dict):
                items = items.get('items') or []
            if items:
                customer_id = items[0].get('id')
                
        if not customer_id:
            return {'success': False, 'error': 'Failed to create customer.'}

        # 2. Create GHS payment method
        pm_url = f"{FLW_SANDBOX_BASE_URL}/payment-methods"
        pm_payload = {
            "type": "mobile_money",
            "customer_id": customer_id,
            "mobile_money": {
                "network": "MTN",
                "country_code": "233",
                "phone_number": "100001001"
            }
        }
        pm_resp = requests.post(pm_url, json=pm_payload, headers=headers, timeout=15)
        pm_data = pm_resp.json()
        payment_method_id = (pm_data.get('data') or {}).get('id')
        
        if not payment_method_id:
            return {'success': False, 'error': pm_data.get('message', 'Failed to create payment method.')}

        # 3. Create charge (using GHS to match GH Mobile Money)
        charge_url = f"{FLW_SANDBOX_BASE_URL}/charges"
        charge_payload = {
            "amount": float(amount),
            "currency": "GHS",
            "reference": tx_ref,
            "customer_id": customer_id,
            "payment_method_id": payment_method_id,
            "meta": {
                "voucher_pin": voucher_pin,
                "source": "komunity_wallet"
            }
        }
        
        charge_headers = get_headers(scenario_key='scenario:charge.succeeded')
        charge_resp = requests.post(charge_url, json=charge_payload, headers=charge_headers, timeout=15)
        charge_data = charge_resp.json()
        
        logger.info(f"[FLW] Sandbox charge result: {charge_data}")
        
        # In sandbox, scenario success yields success/pending with positive charge ID
        if charge_resp.status_code in (200, 201):
            charge_id = charge_data.get('data', {}).get('id') or tx_ref
            return {
                'success': True,
                'amount': amount,
                'waas_ref': charge_id
            }
        else:
            return {'success': False, 'error': charge_data.get('message', 'Charge failed')}
            
    except Exception as e:
        logger.error(f"[FLW] Exception in charge_voucher: {e}")
        return {'success': False, 'error': str(e)}


def _encrypt_card_field(plain_text, key_b64, nonce_str):
    """
    Encrypts a card field using AES-256-GCM as required by Flutterwave v4.
    Returns a base64-encoded ciphertext string.
    """
    key = base64.b64decode(key_b64)
    aesgcm = AESGCM(key)
    nonce = nonce_str.encode('utf-8')
    ciphertext = aesgcm.encrypt(nonce, plain_text.encode('utf-8'), None)
    return base64.b64encode(ciphertext).decode('utf-8')


def charge_card(card_number, expiry_month, expiry_year, cvv, amount, email, phone_number, tx_ref):
    """
    Charges a card in the Flutterwave v4 sandbox.
    1. Creates/retrieves customer.
    2. Encrypts card fields with AES-GCM using FLW_ENCRYPTION_KEY.
    3. Registers a sandbox card payment method.
    4. Triggers simulated charge with scenario key.
    """
    try:
        headers = get_headers()
        enc_key = getattr(settings, 'FLW_ENCRYPTION_KEY', None)
        if not enc_key:
            return {'success': False, 'error': 'FLW_ENCRYPTION_KEY is not configured.'}

        # Generate a fresh 12-char alphanumeric nonce for this transaction
        nonce = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))

        # 1. Create/retrieve customer
        cust_url = f"{FLW_SANDBOX_BASE_URL}/customers"
        cust_payload = {
            "email": email,
            "name": {"first": "Komunity", "last": "User"},
            "phone": {
                "country_code": "27",
                "number": "100001001"
            }
        }
        cust_resp = requests.post(cust_url, json=cust_payload, headers=headers, timeout=15)
        cust_data = cust_resp.json()
        customer_id = (cust_data.get('data') or {}).get('id')

        if not customer_id:
            search_resp = requests.get(f"{cust_url}?email={email}", headers=headers, timeout=15)
            search_data = search_resp.json()
            items = search_data.get('data') or []
            if isinstance(items, dict):
                items = items.get('items') or []
            if items:
                customer_id = items[0].get('id')

        if not customer_id:
            return {'success': False, 'error': 'Failed to create or retrieve customer.'}

        # 2. Encrypt card fields and create payment method
        pm_url = f"{FLW_SANDBOX_BASE_URL}/payment-methods"
        pm_payload = {
            "type": "card",
            "customer_id": customer_id,
            "card": {
                "encrypted_card_number": _encrypt_card_field(card_number, enc_key, nonce),
                "encrypted_expiry_month": _encrypt_card_field(str(expiry_month).zfill(2), enc_key, nonce),
                "encrypted_expiry_year": _encrypt_card_field(str(expiry_year), enc_key, nonce),
                "encrypted_cvv": _encrypt_card_field(str(cvv), enc_key, nonce),
                "nonce": nonce,
            }
        }
        pm_resp = requests.post(pm_url, json=pm_payload, headers=headers, timeout=15)
        pm_data = pm_resp.json()
        payment_method_id = (pm_data.get('data') or {}).get('id')

        if not payment_method_id:
            err = (pm_data.get('error') or {}).get('message') or pm_data.get('message', 'Failed to create card payment method.')
            logger.warning(f"[FLW] Card payment method creation failed: {pm_data}")
            return {'success': False, 'error': err}

        # 3. Create charge
        charge_url = f"{FLW_SANDBOX_BASE_URL}/charges"
        charge_payload = {
            "amount": float(amount),
            "currency": "ZAR",
            "reference": tx_ref,
            "customer_id": customer_id,
            "payment_method_id": payment_method_id,
            "meta": {
                "source": "komunity_wallet",
                "payment_method_type": "card"
            }
        }

        charge_headers = get_headers(scenario_key='scenario:charge.succeeded')
        charge_resp = requests.post(charge_url, json=charge_payload, headers=charge_headers, timeout=15)
        charge_data = charge_resp.json()

        logger.info(f"[FLW] Sandbox card charge result: {charge_data}")

        if charge_resp.status_code in (200, 201):
            charge_id = (charge_data.get('data') or {}).get('id') or tx_ref
            return {
                'success': True,
                'amount': amount,
                'waas_ref': charge_id
            }
        else:
            err = (charge_data.get('error') or {}).get('message') or charge_data.get('message', 'Card charge failed')
            return {'success': False, 'error': err}

    except Exception as e:
        logger.error(f"[FLW] Exception in charge_card: {e}")
        return {'success': False, 'error': str(e)}


def initiate_transfer(amount, bank_code, account_number, narration, reference):
    """
    Initiates a payout transfer to a bank account using the Flutterwave v4 sandbox.
    Uses scenario key to simulate a successful disbursement.
    """
    url = f"{FLW_SANDBOX_BASE_URL}/transfers"
    payload = {
        "amount": float(amount),
        "currency": "ZAR",
        "reference": reference,
        "narration": narration,
        "recipient_id": f"SANDBOX_{account_number}",
        "sender_id": f"SANDBOX_KOMUNITY",
        "meta": {
            "bank_code": bank_code,
            "account_number": account_number
        }
    }

    try:
        headers = get_headers(scenario_key='scenario:transfer.succeeded')
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        res_data = response.json()

        logger.info(f"[FLW] initiate_transfer response HTTP {response.status_code}: {res_data}")

        status_val = res_data.get('status') or res_data.get('data', {}).get('status', '')
        if response.status_code in (200, 201) and status_val in ('success', 'succeeded'):
            transfer_id = res_data.get('data', {}).get('id') or reference
            return {'success': True, 'waas_ref': transfer_id}
        else:
            err_msg = (
                res_data.get('error', {}).get('message')
                or res_data.get('message')
                or 'Transfer initiation failed'
            )
            logger.warning(f"[FLW] initiate_transfer failed: {err_msg}")
            return {'success': False, 'error': err_msg}

    except Exception as e:
        logger.error(f"[FLW] initiate_transfer exception: {e}")
        return {'success': False, 'error': str(e)}


def verify_identity(id_number, id_type='national_id', first_name='', surname=''):
    """
    Verifies user identity document using Flutterwave Identity API.
    Supports national_id, passport, driver_license, and country-specific ID numbers.
    """
    url = f"{FLW_SANDBOX_BASE_URL}/identity-verifications"
    payload = {
        "id_number": id_number,
        "type": id_type,
        "first_name": first_name,
        "last_name": surname,
        "country": "ZA"
    }

    try:
        headers = get_headers()
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        res_data = response.json()

        logger.info(f"[FLW] Identity verification response HTTP {response.status_code}: {res_data}")

        if response.status_code in (200, 201) and res_data.get('status') == 'success':
            return {
                'success': True,
                'message': 'Identity document verified successfully via Flutterwave.',
                'data': res_data.get('data', {})
            }
        else:
            err_msg = (
                (res_data.get('error') or {}).get('message')
                or res_data.get('message')
                or 'Identity verification failed.'
            )
            return {'success': False, 'error': err_msg}

    except Exception as e:
        logger.error(f"[FLW] verify_identity exception: {e}")
        return {'success': False, 'error': str(e)}

