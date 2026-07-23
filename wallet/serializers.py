from rest_framework import serializers
from .models import Wallet, Transaction, GroupWalletTransferRequest
from chema.serializers import GroupSerializer
from user.serializers import ProfileSerializer

class GroupWalletTransferRequestSerializer(serializers.ModelSerializer):
    group_detail = GroupSerializer(source='group', read_only=True)
    requested_by_detail = serializers.SerializerMethodField()
    recipient_profile_detail = ProfileSerializer(source='recipient_profile', read_only=True)
    approvals_count = serializers.SerializerMethodField()
    current_user_has_approved = serializers.SerializerMethodField()
    can_execute = serializers.SerializerMethodField()

    class Meta:
        model = GroupWalletTransferRequest
        fields = [
            'id', 'group', 'group_detail', 'requested_by', 'requested_by_detail',
            'recipient_profile', 'recipient_profile_detail', 'amount', 'status',
            'approvals_count', 'current_user_has_approved', 'can_execute',
            'deceased_contribution', 'fund_campaign',
            'created_at', 'updated_at', 'executed_at'
        ]
        read_only_fields = ['status', 'approvals_count', 'current_user_has_approved', 'created_at', 'updated_at', 'executed_at']

    def get_requested_by_detail(self, obj):
        if obj.requested_by:
            profile = getattr(obj.requested_by, 'profile', None)
            if profile:
                return {
                    'id': profile.id,
                    'full_name': profile.full_name,
                    'email': profile.email,
                }
        return None

    def get_approvals_count(self, obj):
        return obj.approvals.count()

    def get_current_user_has_approved(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.approvals.filter(id=request.user.id).exists()
        return False

    def get_can_execute(self, obj):
        return obj.can_execute()


class TransactionSerializer(serializers.ModelSerializer):
    destination_group_detail = GroupSerializer(source='destination_group', read_only=True)
    recipient_wallet_detail = serializers.SerializerMethodField()
    wallet_detail = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'wallet', 'transaction_type', 'amount', 'status', 
            'withdrawal_channel', 'withdrawal_metadata',
            'destination_group', 'destination_group_detail', 
            'recipient_wallet', 'recipient_wallet_detail',
            'wallet_detail',
            'deceased_contribution', 'voucher_reference', 
            'waas_reference_id', 'timestamp'
        ]
    
    def get_wallet_detail(self, obj):
        user = obj.wallet.user
        return {
            'user_id': user.id,
            'user_phone': user.phone,
            'full_name': user.profile.full_name if hasattr(user, 'profile') else str(user)
        }
    
    def get_recipient_wallet_detail(self, obj):
        if obj.recipient_wallet:
            return {
                'user_id': obj.recipient_wallet.user.id,
                'full_name': obj.recipient_wallet.user.profile.full_name if hasattr(obj.recipient_wallet.user, 'profile') else str(obj.recipient_wallet.user)
            }
        return None

class WalletSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(source='get_balance', max_digits=10, decimal_places=2, read_only=True)
    recent_transactions = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = ['id', 'user', 'external_wallet_id', 'balance', 'recent_transactions', 'created_at']

    def get_recent_transactions(self, obj):
        transactions = obj.transactions.all().order_by('-timestamp')[:5]
        return TransactionSerializer(transactions, many=True).data
