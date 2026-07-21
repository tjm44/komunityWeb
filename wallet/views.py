from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from django.db import models
from django.utils import timezone
from decimal import Decimal, InvalidOperation
import uuid

from .models import Wallet, Transaction
from chema.models import Group
from condolence.models import Deceased, Contribution
from user.models import CustomUser
from .flutterwave import charge_voucher, initiate_transfer

# --- Helper Flutterwave Functions ---

def waas_api_redeem_voucher(voucher_pin, user_wallet_id, email, phone_number, tx_ref):
    # Charges a South African ZAR 1Voucher PIN using Flutterwave Sandbox
    # In test mode, we map PIN "50" to 50.00 ZAR and others to 100.00 ZAR
    amount = Decimal('100.00')
    if voucher_pin == "50":
        amount = Decimal('50.00')
    
    return charge_voucher(
        voucher_pin=voucher_pin,
        amount=amount,
        email=email,
        phone_number=phone_number or '0000000000',
        tx_ref=tx_ref
    )

def waas_api_transfer_funds(from_wallet_id, to_wallet_id, amount):
    # Initiates a transfer payout using Flutterwave Sandbox
    ref = f"transfer-{uuid.uuid4().hex[:8]}"
    return initiate_transfer(
        amount=amount,
        bank_code="044",  # Standard mock bank code
        account_number="0690000031",  # Standard mock account number
        narration=f"Transfer from {from_wallet_id} to {to_wallet_id}",
        reference=ref
    )

def waas_api_get_balance(wallet_id):
    # In a real app, this would query the WaaS provider for the live balance
    return {'success': True, 'balance': Decimal('150.00')}


# --- Views ---

@login_required
@require_POST
def top_up_with_voucher(request):
    """
    HTMX view: Redeems a voucher and updates the user's wallet.
    """
    voucher_pin = request.POST.get('voucher_pin')
    user_wallet, created = Wallet.objects.get_or_create(user=request.user, defaults={'external_wallet_id': f"auto_{request.user.email}"})

    # 1. Log PENDING
    log_entry = Transaction.objects.create(
        wallet=user_wallet,
        transaction_type=Transaction.TransactionType.TOP_UP,
        amount=0.00,
        status=Transaction.TransactionStatus.PENDING,
        voucher_reference=voucher_pin
    )

    # Generate a unique reference
    tx_ref = f"topup-{log_entry.id}-{uuid.uuid4().hex[:6]}"
    phone = getattr(request.user.profile, 'phone', '0000000000') or '0000000000'

    # 2. Call API
    api_response = waas_api_redeem_voucher(
        voucher_pin=voucher_pin,
        user_wallet_id=user_wallet.external_wallet_id,
        email=request.user.email,
        phone_number=phone,
        tx_ref=tx_ref
    )


    if api_response['success']:
        # 3. Update Log & Balance atomically
        with db_transaction.atomic():
            log_entry.status = Transaction.TransactionStatus.COMPLETED
            log_entry.amount = api_response['amount']
            log_entry.waas_reference_id = api_response['waas_ref']
            log_entry.save()
            
            # Increment balance
            user_wallet = Wallet.objects.select_for_update().get(id=user_wallet.id)
            user_wallet.balance += log_entry.amount
            user_wallet.save(update_fields=['balance'])
        
        # 4. Return success signal to HTMX
        import json
        triggers = {'update-balance': True, 'close-top-up-modal': True, 'update-history': True}
        return HttpResponse("", status=200, headers={'HX-Trigger': json.dumps(triggers)})
    else:
        # 3. Mark Failed
        log_entry.status = Transaction.TransactionStatus.FAILED
        log_entry.save()
        return HttpResponse(f"<span class='text-red-500 text-sm'>{api_response['error']}</span>")


@login_required
@require_POST
def transfer_to_group(request, group_id):
    """
    HTMX view: Transfers money from user to group for a specific deceased campaign.
    """
    try:
        amount = Decimal(request.POST.get('amount'))
        deceased_id = request.POST.get('deceased_id')
    except (ValueError, TypeError):
         return HttpResponse(f"<span class='text-red-500 text-sm'>Invalid amount</span>")
    
    # Validate deceased_id
    if not deceased_id:
        return HttpResponse(f"<span class='text-red-500 text-sm'>Please select a campaign</span>")
    
    deceased = get_object_or_404(Deceased, pk=deceased_id, cont_is_active=True)
    group = deceased.group
    
    if Contribution.objects.filter(deceased_member=deceased, contributing_member=request.user.profile).exists():
        return HttpResponse(f"<span class='text-red-500 text-sm'>You have already contributed to this campaign.</span>")

    with db_transaction.atomic():
        user_wallet = Wallet.objects.select_for_update().get(user=request.user)

        if user_wallet.get_balance() < amount:
            return HttpResponse(f"<span class='text-red-500 text-sm'>Insufficient wallet balance.</span>")

        # Deduct balance immediately inside lock
        user_wallet.balance -= amount
        user_wallet.save(update_fields=['balance'])

        log_entry = Transaction.objects.create(
            wallet=user_wallet,
            transaction_type=Transaction.TransactionType.TRANSFER,
            amount=amount,
            status=Transaction.TransactionStatus.PENDING,
            destination_group=group,
            deceased_contribution=deceased
        )
    
    # Call API outside long lock if needed, or handle mock transfer
    api_response = waas_api_transfer_funds(
        from_wallet_id=user_wallet.external_wallet_id,
        to_wallet_id=group.external_wallet_id,
        amount=amount
    )
    
    with db_transaction.atomic():
        log_entry = Transaction.objects.select_for_update().get(id=log_entry.id)
        if api_response['success']:
            log_entry.status = Transaction.TransactionStatus.COMPLETED
            log_entry.waas_reference_id = api_response['waas_ref']
            log_entry.save()
            
            Contribution.objects.create(
                group=group,
                deceased_member=deceased,
                contributing_member=request.user.profile,
                amount=amount,
                payment_method='WALLET',
                transaction=log_entry
            )
        else:
            log_entry.status = Transaction.TransactionStatus.FAILED
            log_entry.save()
            # Refund wallet on failed transfer
            user_wallet = Wallet.objects.select_for_update().get(user=request.user)
            user_wallet.balance += amount
            user_wallet.save(update_fields=['balance'])
            return HttpResponse(f"<span class='text-red-500 text-sm'>{api_response['error']}</span>")
        
        # 5. Return success
        import json
        triggers = {
            'update-balance': True, 
            'close-transfer-modal': True,
            'update-contributions': True,
            'update-history': True
        }
        return HttpResponse("", status=200, headers={'HX-Trigger': json.dumps(triggers)})


@login_required
@require_POST
def send_p2p_money(request):
    """
    HTMX view: Transfers money from user to another user.
    """
    recipient_email = request.POST.get('recipient_email')
    amount_str = request.POST.get('amount')
    note = request.POST.get('note', '')

    try:
        amount = Decimal(amount_str)
    except (ValueError, TypeError, InvalidOperation):
        return HttpResponse("<span class='text-red-500 text-sm'>Invalid amount</span>")

    if amount <= 0:
        return HttpResponse("<span class='text-red-500 text-sm'>Amount must be positive</span>")

    if not recipient_email:
        return HttpResponse("<span class='text-red-500 text-sm'>Recipient email is required</span>")

    if recipient_email == request.user.email:
        return HttpResponse("<span class='text-red-500 text-sm'>Cannot send money to yourself</span>")

    try:
        recipient_user = CustomUser.objects.get(email=recipient_email)
    except CustomUser.DoesNotExist:
        return HttpResponse("<span class='text-red-500 text-sm'>Recipient not found</span>")

    sender_wallet, _ = Wallet.objects.get_or_create(user=request.user, defaults={'external_wallet_id': f"auto_{request.user.email}"})
    recipient_wallet, _ = Wallet.objects.get_or_create(user=recipient_user, defaults={'external_wallet_id': f"auto_{recipient_user.email}"})

    with db_transaction.atomic():
        # Lock sender and recipient wallets in predictable ID order to prevent deadlocks
        wallet_ids = sorted([sender_wallet.id, recipient_wallet.id])
        wallets = {w.id: w for w in Wallet.objects.select_for_update().filter(id__in=wallet_ids)}
        
        s_wallet = wallets[sender_wallet.id]
        r_wallet = wallets[recipient_wallet.id]

        if s_wallet.balance < amount:
            return HttpResponse("<span class='text-red-500 text-sm'>Insufficient balance</span>")

        # Update balances
        s_wallet.balance -= amount
        r_wallet.balance += amount
        s_wallet.save(update_fields=['balance'])
        r_wallet.save(update_fields=['balance'])

        # Debit transaction record for sender
        sender_txn = Transaction.objects.create(
            wallet=s_wallet,
            transaction_type=Transaction.TransactionType.P2P_SENT,
            amount=amount,
            status=Transaction.TransactionStatus.COMPLETED,
            sender_wallet=s_wallet,
            recipient_wallet=r_wallet,
            waas_reference_id=api_response['waas_ref']
        )

        # Credit to recipient
        recipient_txn = Transaction.objects.create(
            wallet=recipient_wallet,
            transaction_type=Transaction.TransactionType.P2P_RECEIVED,
            amount=amount,
            status=Transaction.TransactionStatus.COMPLETED,
            sender_wallet=sender_wallet,
            recipient_wallet=recipient_wallet,
            waas_reference_id=api_response['waas_ref']
        )

    import json
    triggers = {
        'update-balance': True,
        'close-p2p-modal': True,
        'update-history': True
    }
    return HttpResponse("", status=200, headers={'HX-Trigger': json.dumps(triggers)})


@login_required
def get_wallet_balance_snippet(request):
    """
    HTMX view: Returns just the HTML for the wallet balance.
    """
    # Ensure wallet exists
    user_wallet, created = Wallet.objects.get_or_create(user=request.user, defaults={'external_wallet_id': f"auto_{request.user.email}"})
    
    balance = user_wallet.get_balance()
    
    return HttpResponse(f"R {balance}")

@login_required
def transaction_history(request):
    """
    View to display the user's transaction history.
    """
    user_wallet, created = Wallet.objects.get_or_create(user=request.user, defaults={'external_wallet_id': f"auto_{request.user.email}"})
    transactions = Transaction.objects.filter(wallet=user_wallet).order_by('-timestamp')
    
    context = {
        'transactions': transactions,
        'wallet': user_wallet,
        'balance': user_wallet.get_balance(),
    }
    
    if request.headers.get('HX-Request') and not request.headers.get('HX-Target') == 'main-content':
        # If it's a targeted HTMX request (like update-history), return just the list
        return render(request, 'wallet/partials/transaction_list.html', context)
        
    return render(request, 'wallet/history.html', context)

@login_required
def group_transaction_history(request, group_id):
    """
    View to display the transaction history for a specific group.
    """
    group = get_object_or_404(Group, pk=group_id)
    
    # Permission: Any member of the group can view for transparency
    if not group.is_member(request.user):
        return HttpResponse("Unauthorized", status=403)
    
    # All transactions where this group is the destination
    transactions = Transaction.objects.filter(destination_group=group).order_by('-timestamp')
    
    # Calculate group balance (Sum of transfers - Sum of payouts)
    from django.db.models import Sum
    incoming = transactions.filter(transaction_type='TRANSFER', status='COMPLETED').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    outgoing = transactions.filter(transaction_type='PAYOUT_RECEIVED', status='COMPLETED').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    balance = incoming - outgoing
    
    context = {
        'group': group,
        'transactions': transactions,
        'balance': balance,
        'is_admin': group.is_admin(request.user)
    }
    
    if request.headers.get('HX-Request') and not request.headers.get('HX-Target') == 'main-content':
        return render(request, 'wallet/partials/group_transaction_list.html', context)
        
    return render(request, 'wallet/group_history.html', context)
