import json
import logging
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db import transaction as db_transaction

from .models import Wallet, Transaction

logger = logging.getLogger(__name__)

@csrf_exempt
@require_POST
def flutterwave_webhook(request):
    """
    Webhook listener for Flutterwave v4 event notifications.
    Validates verif-hash signature header and idempotently processes charge & transfer events.
    """
    secret_hash = getattr(settings, 'FLW_WEBHOOK_SECRET_HASH', None)
    signature = request.headers.get('verif-hash') or request.headers.get('Verif-Hash')

    # Security check: Validate signature header if secret hash is configured
    if secret_hash and signature != secret_hash:
        logger.warning("Flutterwave Webhook: Invalid secret hash signature.")
        return HttpResponse(status=401)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception as e:
        logger.error(f"Flutterwave Webhook: Failed to parse JSON body - {e}")
        return JsonResponse({'status': 'invalid json'}, status=400)

    event_type = payload.get('type') or payload.get('event')
    data = payload.get('data', {})

    logger.info(f"Flutterwave Webhook received event: {event_type}")

    # Process charge completion (Deposit / Top-up)
    if event_type in ['charge.completed', 'charge.succeeded']:
        return handle_charge_completed(data)

    # Process transfer disbursement (Withdrawal / Payout)
    elif event_type in ['transfer.disburse', 'transfer.completed', 'transfer.failed']:
        return handle_transfer_disburse(data)

    return JsonResponse({'status': 'ignored'}, status=200)


def handle_charge_completed(data):
    tx_ref = data.get('reference') or data.get('tx_ref')
    amount_val = data.get('amount')
    status_val = data.get('status')
    flw_id = str(data.get('id', ''))

    if status_val not in ['successful', 'succeeded', 'SUCCESSFUL', 'COMPLETED']:
        logger.info(f"Flutterwave Webhook: Charge status '{status_val}' is not successful for ref {tx_ref}")
        return JsonResponse({'status': 'skipped non-success status'}, status=200)

    try:
        amount = Decimal(str(amount_val))
    except (TypeError, ValueError, InvalidOperation):
        amount = Decimal('0.00')

    with db_transaction.atomic():
        # Match by waas_reference_id or idempotency_key or voucher_reference
        tx = Transaction.objects.select_for_update().filter(
            idempotency_key=tx_ref
        ).first()

        if not tx:
            tx = Transaction.objects.select_for_update().filter(
                waas_reference_id=flw_id
            ).first()

        if not tx:
            logger.warning(f"Flutterwave Webhook: Transaction ref {tx_ref} not found locally.")
            return JsonResponse({'status': 'transaction not found'}, status=200)

        # Idempotency check: Skip if already processed
        if tx.status == Transaction.TransactionStatus.COMPLETED:
            logger.info(f"Flutterwave Webhook: Transaction {tx.id} already completed.")
            return JsonResponse({'status': 'already processed'}, status=200)

        tx.status = Transaction.TransactionStatus.COMPLETED
        tx.waas_reference_id = flw_id
        if amount > 0:
            tx.amount = amount
        tx.save()

        # Atomically credit wallet balance
        wallet = Wallet.objects.select_for_update().get(id=tx.wallet_id)
        wallet.balance += tx.amount
        wallet.save(update_fields=['balance'])

        logger.info(f"Flutterwave Webhook: Credited {tx.amount} to Wallet {wallet.id}")

    return JsonResponse({'status': 'success'}, status=200)


def handle_transfer_disburse(data):
    tx_ref = data.get('reference')
    status_val = data.get('status')
    flw_id = str(data.get('id', ''))

    is_success = status_val in ['successful', 'succeeded', 'SUCCESSFUL', 'COMPLETED']
    is_failed = status_val in ['failed', 'FAILED', 'REJECTED']

    with db_transaction.atomic():
        tx = Transaction.objects.select_for_update().filter(
            idempotency_key=tx_ref
        ).first()

        if not tx:
            tx = Transaction.objects.select_for_update().filter(
                waas_reference_id=flw_id
            ).first()

        if not tx:
            logger.warning(f"Flutterwave Webhook: Payout ref {tx_ref} not found locally.")
            return JsonResponse({'status': 'transaction not found'}, status=200)

        if tx.status in [Transaction.TransactionStatus.COMPLETED, Transaction.TransactionStatus.FAILED]:
            return JsonResponse({'status': 'already processed'}, status=200)

        if is_success:
            tx.status = Transaction.TransactionStatus.COMPLETED
            tx.save()
            logger.info(f"Flutterwave Webhook: Payout {tx.id} marked COMPLETED.")

        elif is_failed:
            tx.status = Transaction.TransactionStatus.FAILED
            tx.save()

            # Refund user's locked balance on failed payout
            wallet = Wallet.objects.select_for_update().get(id=tx.wallet_id)
            wallet.balance += tx.amount
            wallet.save(update_fields=['balance'])
            logger.info(f"Flutterwave Webhook: Refunded {tx.amount} to Wallet {wallet.id} due to failed payout.")

    return JsonResponse({'status': 'processed'}, status=200)
