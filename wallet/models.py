from django.conf import settings
from django.db import models, transaction as db_transaction
from django.utils import timezone
from chema.models import Group

class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    external_wallet_id = models.CharField(max_length=100, unique=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Wallet for {self.user}"

    def recalculate_balance(self):
        from decimal import Decimal
        from django.db.models import Sum
        
        # Calculate Incoming (Top-Ups + Payouts + Received Transfers)
        incoming = self.transactions.filter(
            transaction_type__in=['TOP_UP', 'PAYOUT_RECEIVED', 'P2P_RECEIVED'],
            status='COMPLETED'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # Calculate Outgoing (Transfers + Withdrawals + Sent Transfers)
        outgoing = self.transactions.filter(
            transaction_type__in=['TRANSFER', 'WITHDRAWAL', 'P2P_SENT'],
            status='COMPLETED'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        calculated = incoming - outgoing
        if self.balance != calculated:
            self.balance = calculated
            self.save(update_fields=['balance'])
        return calculated

    def get_balance(self):
        return self.balance

class Transaction(models.Model):
    class TransactionType(models.TextChoices):
        TOP_UP = 'TOP_UP', 'Top-Up'
        TRANSFER = 'TRANSFER', 'Transfer to Group'
        WITHDRAWAL = 'WITHDRAWAL', 'Withdrawal'
        PAYOUT_RECEIVED = 'PAYOUT_RECEIVED', 'Payout Received'
        P2P_SENT = 'P2P_SENT', 'Peer-to-Peer Sent'
        P2P_RECEIVED = 'P2P_RECEIVED', 'Peer-to-Peer Received'

    class TransactionStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'

    class TransactionChannel(models.TextChoices):
        BANK_TRANSFER = 'bank_transfer', 'Bank Transfer'
        MOBILE_MONEY = 'mobile_money', 'Mobile Money'
        VOUCHER = 'voucher', 'Voucher Cash-out'

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=TransactionStatus.choices, default=TransactionStatus.PENDING)
    withdrawal_channel = models.CharField(max_length=30, choices=TransactionChannel.choices, blank=True, null=True)
    withdrawal_metadata = models.JSONField(blank=True, null=True)

    # Where the money went (if applicable)
    destination_group = models.ForeignKey(Group, on_delete=models.SET_NULL, null=True, blank=True)
    destination_organisation = models.ForeignKey('chema.Organisation', on_delete=models.SET_NULL, null=True, blank=True)
    recipient_wallet = models.ForeignKey(Wallet, on_delete=models.SET_NULL, null=True, blank=True, related_name="incoming_transfers")
    sender_wallet = models.ForeignKey(Wallet, on_delete=models.SET_NULL, null=True, blank=True, related_name="outgoing_p2p_transfers")
    # Legacy: links to a Deceased record (bereavement condolence system)
    deceased_contribution = models.ForeignKey(
        'condolence.Deceased', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='wallet_contributions'
    )
    # New: links to a generic FundCampaign (excess, emergency, custom)
    fund_campaign = models.ForeignKey(
        'condolence.FundCampaign', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='campaign_transactions',
        help_text="Links this transaction to a generic FundCampaign"
    )

    # IDs from the external systems for reconciliation
    voucher_reference = models.CharField(max_length=100, blank=True, null=True)
    waas_reference_id = models.CharField(max_length=100, blank=True, null=True)  # The ID from your WaaS provider
    idempotency_key = models.CharField(max_length=100, unique=True, null=True, blank=True)
    note = models.CharField(max_length=512, blank=True, null=True, help_text="Human-readable purpose/description of this transaction")
    
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.transaction_type} of {self.amount} for {self.wallet.user} - {self.status}"


class GroupWalletTransferRequest(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_EXECUTED = 'EXECUTED'
    STATUS_REJECTED = 'REJECTED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_EXECUTED, 'Executed'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    REQUIRED_APPROVALS = 3

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='wallet_transfer_requests')
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='group_wallet_transfer_requests'
    )
    recipient_profile = models.ForeignKey(
        'user.Profile',
        on_delete=models.CASCADE,
        related_name='group_wallet_transfer_requests'
    )
    recipient_wallet = models.ForeignKey(
        Wallet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_group_transfer_requests'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    deceased_contribution = models.ForeignKey(
        'condolence.Deceased', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='wallet_transfer_requests'
    )
    fund_campaign = models.ForeignKey(
        'condolence.FundCampaign', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='campaign_transfer_requests',
        help_text="Links this transfer request to a generic FundCampaign"
    )
    approvals = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='approved_group_transfer_requests',
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    executed_transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='executed_group_transfer_requests'
    )

    def __str__(self):
        return f"{self.group.name} transfer request {self.amount} to {self.recipient_profile.full_name} ({self.status})"

    def can_execute(self):
        return (
            self.status == self.STATUS_PENDING and
            self.approvals.count() >= self.REQUIRED_APPROVALS and
            self.group.get_balance() >= self.amount
        )

    def execute(self):
        if self.status != self.STATUS_PENDING:
            raise ValueError('Only pending transfer requests can be executed.')

        if self.approvals.count() < self.REQUIRED_APPROVALS:
            raise ValueError('Not enough approvals to execute this transfer request.')

        if self.group.get_balance() < self.amount:
            raise ValueError('Insufficient group wallet balance to execute the transfer.')

        with db_transaction.atomic():
            recipient_wallet, _ = Wallet.objects.get_or_create(
                user=self.recipient_profile.user,
                defaults={'external_wallet_id': f"WAAS_{self.recipient_profile.user.id}"}
            )

            transaction = Transaction.objects.create(
                wallet=recipient_wallet,
                transaction_type='PAYOUT_RECEIVED',
                amount=self.amount,
                status='COMPLETED',
                destination_group=self.group,
                deceased_contribution=self.deceased_contribution,
                fund_campaign=self.fund_campaign,
                waas_reference_id=f"GROUP_TRANSFER_{timezone.now().timestamp()}"
            )
            recipient_wallet.recalculate_balance()

            self.recipient_wallet = recipient_wallet
            self.executed_transaction = transaction
            self.status = self.STATUS_EXECUTED
            self.executed_at = timezone.now()
            self.save()
