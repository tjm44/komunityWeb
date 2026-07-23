import uuid
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.pagination import PageNumberPagination
from rest_framework.authtoken.models import Token
from rest_framework.views import APIView
from django.contrib.auth import authenticate
from rest_framework import serializers as drf_serializers
from rest_framework.exceptions import PermissionDenied, ValidationError


class StandardPagination(PageNumberPagination):
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 50


class EmailAuthTokenSerializer(drf_serializers.Serializer):
    """Accepts email + password instead of username + password."""
    email = drf_serializers.EmailField(label='Email')
    password = drf_serializers.CharField(
        label='Password',
        style={'input_type': 'password'},
        trim_whitespace=False
    )

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        from django.contrib.auth import get_user_model
        UserModel = get_user_model()

        # Check if user exists but is not active (email not verified)
        try:
            user_obj = UserModel.objects.get(email__iexact=email)
            if not user_obj.is_active:
                raise drf_serializers.ValidationError(
                    'Your account has not been verified. Please check your email to verify your account.',
                    code='not_verified'
                )
        except UserModel.DoesNotExist:
            raise drf_serializers.ValidationError(
                'No account found with this email address.',
                code='no_account'
            )

        user = authenticate(
            request=self.context.get('request'),
            username=email,  # Django backend uses USERNAME_FIELD which is 'email'
            password=password
        )

        if not user:
            raise drf_serializers.ValidationError(
                'Incorrect password. Please try again.',
                code='authorization'
            )

        attrs['user'] = user
        return attrs


class EmailAuthTokenView(APIView):
    """Custom token endpoint: POST {email, password} -> {token}"""
    permission_classes = [AllowAny]
    serializer_class = EmailAuthTokenSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, created = Token.objects.get_or_create(user=user)
        return Response({'token': token.key})


class CheckPhoneStatusView(APIView):
    """
    Endpoint: POST /api/v1/auth/check-phone/
    Body: {"phone": "+254..."}
    Returns {"has_pin": true/false, "user_exists": true/false}
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from user.models import CustomUser
        phone = request.data.get('phone', '').strip().replace(" ", "").replace("-", "")
        if not phone:
            return Response({'error': 'Phone number is required.'}, status=status.HTTP_400_BAD_REQUEST)

        user = CustomUser.objects.filter(phone=phone).first()
        return Response({
            'user_exists': bool(user),
            'has_pin': bool(user and user.has_pin)
        }, status=status.HTTP_200_OK)


class RequestOTPView(APIView):
    """
    Endpoint: POST /api/v1/auth/request-otp/
    Body: {"phone": "+254..."}
    Generates a 6-digit OTP, saves it in PhoneOTP with a 10-minute expiry, and dispatches SMS.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        import random
        from datetime import timedelta
        from django.conf import settings
        from user.models import PhoneOTP, CustomUser
        from user.sms import send_otp_sms

        phone = request.data.get('phone', '').strip().replace(" ", "").replace("-", "")
        if not phone:
            return Response({'error': 'Phone number is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Generate 6-digit OTP
        otp = f"{random.randint(100000, 999999)}"
        expires_at = timezone.now() + timedelta(minutes=10)

        # Save to DB
        PhoneOTP.objects.create(
            phone=phone,
            otp=otp,
            expires_at=expires_at
        )

        # Dispatch SMS
        send_otp_sms(phone, otp)

        user = CustomUser.objects.filter(phone=phone).first()

        return Response({
            'message': 'OTP sent successfully.',
            'phone': phone,
            'has_pin': bool(user and user.has_pin),
            'dev_otp': otp if getattr(settings, 'DEBUG', False) else None
        }, status=status.HTTP_200_OK)


class VerifyOTPView(APIView):
    """
    Endpoint: POST /api/v1/auth/verify-otp/
    Body: {"phone": "+254...", "otp": "123456"}
    Verifies OTP, authenticates or registers CustomUser, and returns Auth token + user info.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from django.conf import settings
        from user.models import PhoneOTP, CustomUser, Profile
        from user.serializers import UserSerializer

        phone = request.data.get('phone', '').strip().replace(" ", "").replace("-", "")
        otp = request.data.get('otp', '').strip()

        if not phone or not otp:
            return Response({'error': 'Phone and OTP are required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Look up valid OTP
        otp_record = PhoneOTP.objects.filter(phone=phone, is_verified=False).order_by('-created_at').first()

        # Dev fallback: allow test OTP '123456' in DEBUG mode if needed
        is_dev_test = getattr(settings, 'DEBUG', False) and otp == '123456'

        if not is_dev_test:
            if not otp_record:
                return Response({'error': 'No OTP requested for this phone number.'}, status=status.HTTP_400_BAD_REQUEST)

            if not otp_record.is_valid():
                return Response({'error': 'OTP has expired or already been used. Please request a new one.'}, status=status.HTTP_400_BAD_REQUEST)

            if otp_record.otp != otp:
                otp_record.attempts += 1
                otp_record.save(update_fields=['attempts'])
                return Response({'error': 'Invalid OTP code. Please try again.'}, status=status.HTTP_400_BAD_REQUEST)

            otp_record.is_verified = True
            otp_record.save(update_fields=['is_verified'])

        # Get or Create User
        user = CustomUser.objects.filter(phone=phone).first()
        is_new_user = False
        if not user:
            profile = Profile.objects.filter(phone=phone).first()
            if profile and profile.user:
                user = profile.user
                user.phone = phone
                user.is_phone_verified = True
                user.save()
            else:
                user = CustomUser.objects.create_user(phone=phone)
                user.is_phone_verified = True
                user.is_active = True
                user.save()
                is_new_user = True
                if hasattr(user, 'profile'):
                    user.profile.phone = phone
                    user.profile.save()

        if hasattr(user, 'profile') and not user.profile.phone:
            user.profile.phone = phone
            user.profile.save()

        token, _ = Token.objects.get_or_create(user=user)
        user_serializer = UserSerializer(user)

        return Response({
            'token': token.key,
            'is_new_user': is_new_user,
            'has_pin': bool(user.has_pin),
            'user': user_serializer.data
        }, status=status.HTTP_200_OK)


class VerifyPINView(APIView):
    """
    Endpoint: POST /api/v1/auth/verify-pin/
    Body: {"phone": "+254...", "pin": "1234"}
    Verifies 4-digit security PIN and returns Auth token + user info.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from user.models import CustomUser
        from user.serializers import UserSerializer

        phone = request.data.get('phone', '').strip().replace(" ", "").replace("-", "")
        pin = request.data.get('pin', '').strip()

        if not phone or not pin:
            return Response({'error': 'Phone number and 4-digit PIN are required.'}, status=status.HTTP_400_BAD_REQUEST)

        user = CustomUser.objects.filter(phone=phone).first()
        if not user or not user.has_pin:
            return Response({'error': 'No security PIN set for this account. Please verify via SMS OTP.'}, status=status.HTTP_400_BAD_REQUEST)

        if not user.check_pin(pin):
            return Response({'error': 'Incorrect 4-digit PIN. Please try again.'}, status=status.HTTP_400_BAD_REQUEST)

        token, _ = Token.objects.get_or_create(user=user)
        user_serializer = UserSerializer(user)

        return Response({
            'token': token.key,
            'has_pin': True,
            'user': user_serializer.data
        }, status=status.HTTP_200_OK)


class SetPINView(APIView):
    """
    Endpoint: POST /api/v1/auth/set-pin/
    Body: {"phone": "+254...", "pin": "1234"}
    Sets or updates the 4-digit security PIN for the user.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from user.models import CustomUser

        phone = request.data.get('phone', '').strip().replace(" ", "").replace("-", "")
        pin = request.data.get('pin', '').strip()

        if not pin or len(pin) != 4 or not pin.isdigit():
            return Response({'error': 'PIN must be exactly 4 digits.'}, status=status.HTTP_400_BAD_REQUEST)

        user = None
        if request.user and request.user.is_authenticated:
            user = request.user
        elif phone:
            user = CustomUser.objects.filter(phone=phone).first()

        if not user:
            return Response({'error': 'User account not found.'}, status=status.HTTP_400_BAD_REQUEST)

        user.set_pin(pin)

        return Response({
            'message': '4-digit security PIN updated successfully.',
            'has_pin': True
        }, status=status.HTTP_200_OK)


from django.shortcuts import get_object_or_404
from django.utils import timezone
from decimal import Decimal

from django.db.models import Q
from chema.models import Group, Post, Comment, GroupMembership, PostImage, Reply, Organisation
from user.models import Profile
from condolence.models import Contribution, Deceased
from wallet.models import Wallet, Transaction, GroupWalletTransferRequest

from chema.serializers import (
    GroupSerializer, PostSerializer, CommentSerializer, 
    GroupMembershipSerializer, PostImageSerializer, ReplySerializer,
    OrganisationSerializer
)
from user.serializers import ProfileSerializer, UserSerializer, SignupSerializer
from condolence.serializers import ContributionSerializer, DeceasedSerializer
from wallet.serializers import WalletSerializer, TransactionSerializer, GroupWalletTransferRequestSerializer

from django.contrib.auth import get_user_model
CustomUser = get_user_model()

from user.notifications import send_push_notification


def waas_api_withdraw(wallet_id, channel, metadata, amount, currency='ZAR'):
    """Call Flutterwave sandbox transfer/disbursement endpoints."""
    from wallet.flutterwave import initiate_transfer
    
    print(f"Flutterwave: Withdrawing {amount} {currency} from {wallet_id} via {channel}")

    if channel == 'bank_transfer':
        acc_num = metadata.get('account_number')
        bank_code = metadata.get('bank_code')
        if not acc_num or not bank_code:
            return {'success': False, 'error': 'Bank account number and bank code are required.'}
        
        # Call initiate_transfer
        ref = f"withdraw-bank-{uuid.uuid4().hex[:8]}"
        res = initiate_transfer(
            amount=amount,
            bank_code=bank_code,
            account_number=acc_num,
            narration=f"Withdraw to Bank Account {acc_num}",
            reference=ref
        )
        return res

    elif channel == 'mobile_money':
        phone = metadata.get('phone_number')
        provider = metadata.get('provider')
        if not phone or not provider:
            return {'success': False, 'error': 'Mobile money phone number and provider are required.'}
        
        # Mobile money payout in Flutterwave is also a transfer
        ref = f"withdraw-momo-{uuid.uuid4().hex[:8]}"
        res = initiate_transfer(
            amount=amount,
            bank_code=provider,  # Network code (e.g. MTN, VODAFONE)
            account_number=phone,
            narration=f"Withdraw to MoMo {phone}",
            reference=ref
        )
        return res

    elif channel == 'voucher':
        # Flutterwave v4 does not support custom voucher payout generation in standard payout sandbox directly, 
        # so we fallback to a simulated success reference.
        partner = metadata.get('partner')
        if not partner:
            return {'success': False, 'error': 'Retail partner is required.'}
        
        import random
        # Generate a simulated voucher code
        voucher_code = f"VAL-{random.randint(100000, 999999)}"
        metadata['voucher_code'] = voucher_code
        
        return {
            'success': True,
            'waas_ref': f"WD_VOUCHER_{timezone.now().timestamp()}"
        }
    else:
        return {'success': False, 'error': 'Unsupported withdrawal channel.'}

class IsAuthorOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to edit it.
    """
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.author == request.user.profile

class IsPostImageAuthorOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners of the post to delete its images.
    """
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.post.author == request.user.profile

class ProfileViewSet(viewsets.ModelViewSet):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer

    def get_queryset(self):
        # Allow users to only see their own profile or public profiles
        if self.request.user.is_authenticated:
            return Profile.objects.filter(is_active=True)
        return Profile.objects.none()

    @action(detail=False, methods=['get'])
    def me(self, request):
        serializer = self.get_serializer(request.user.profile)
        return Response(serializer.data)

    def perform_update(self, serializer):
        profile = serializer.save()
        profile.check_completion()
        profile.save()

    @action(detail=True, methods=['post'], url_path='verify-kyc')
    def verify_kyc(self, request, pk=None):
        profile = self.get_object()
        if profile.user != request.user:
            return Response({'error': 'You can only verify your own profile.'}, status=status.HTTP_403_FORBIDDEN)
            
        id_number = request.data.get('id_number')
        id_type = request.data.get('id_type', 'national_id')
        
        from user.kyc import MockKYCProvider
        success, message = MockKYCProvider.verify_document(
            first_name=profile.first_name,
            surname=profile.surname,
            id_number=id_number,
            id_type=id_type
        )
        
        if not success:
            return Response({'error': message}, status=status.HTTP_400_BAD_REQUEST)
            
        profile.is_verified = True
        profile.save()
        return Response({'status': 'verified', 'message': message}, status=status.HTTP_200_OK)

class UserViewSet(viewsets.GenericViewSet):
    queryset = CustomUser.objects.all()
    serializer_class = UserSerializer

    @action(detail=False, methods=['get'])
    def me(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny])
    def signup(self, request):
        serializer = SignupSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response(UserSerializer(user, context={'request': request}).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class GroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer

    def perform_create(self, serializer):
        group = serializer.save(creator=self.request.user)
        # Ensure the creator active admin membership is upserted without duplicate creation
        GroupMembership.objects.update_or_create(
            group=group,
            member=self.request.user.profile,
            defaults={
                'is_admin': True,
                'role': 'admin',
                'status': 'active',
                'is_active': True
            }
        )
        # Deactivate others for this user to keep only one active
        GroupMembership.objects.filter(member=self.request.user.profile).exclude(group=group).update(is_active=False)

    def get_queryset(self):
        queryset = Group.objects.filter(is_active=True).order_by('-created_at')
        
        # Discovery Logic: Exclude groups the user is already an active member of
        # ONLY apply this to the list action, not detail actions like members or leave
        if self.action == 'list' and self.request.user.is_authenticated:
            queryset = queryset.exclude(
                groupmembership__member=self.request.user.profile,
                groupmembership__status='active'
            ).distinct()
        return queryset

    @action(detail=False, methods=['get'])
    def mine(self, request):
        profile = request.user.profile
        
        if request.GET.get('active') == 'true':
            groups = Group.objects.filter(
                groupmembership__member=profile,
                groupmembership__status='active',
                groupmembership__is_active=True
            ).distinct()
        else:
            groups = Group.objects.filter(
                groupmembership__member=profile,
                groupmembership__status='active'
            ).distinct()
            
        serializer = self.get_serializer(groups, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def active_members(self, request):
        active_mem = GroupMembership.objects.filter(member=request.user.profile, is_active=True).first()
        if not active_mem:
            return Response([])
        
        # Changed to handle the case where some memberships might be 'deceased' but we still want to see them in some lists?
        # Actually for sending money, only active 'active' members.
        memberships = GroupMembership.objects.filter(group=active_mem.group, status='active')
        serializer = GroupMembershipSerializer(memberships, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def discover(self, request):
        # This will use get_queryset() which already filters out joined groups if action is 'list'
        # But we want to be explicit here
        queryset = Group.objects.filter(is_active=True).exclude(
            groupmembership__member=request.user.profile,
            groupmembership__status='active'
        ).distinct().order_by('-created_at')
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def join(self, request, pk=None):
        group = self.get_object()
        profile = request.user.profile
        if group.verified_members_only and not profile.is_verified:
            return Response({'error': 'This group is restricted to verified profiles only.'}, status=status.HTTP_400_BAD_REQUEST)

        # Creators always rejoin as active admins, regardless of group settings
        is_creator = (group.creator == request.user)
        if is_creator:
            membership, _ = GroupMembership.objects.get_or_create(
                group=group,
                member=profile,
                defaults={
                    'status': 'active',
                    'is_active': True,
                    'is_admin': True,
                    'role': 'admin',
                }
            )
            # Ensure creator always has full admin rights even if membership pre-existed
            if not (membership.is_admin and membership.role == 'admin' and membership.status == 'active' and membership.is_active):
                membership.is_admin = True
                membership.role = 'admin'
                membership.status = 'active'
                membership.is_active = True
                membership.save()
            # Deactivate others for this user to keep only one active
            GroupMembership.objects.filter(member=profile).exclude(group=group).update(is_active=False)
            return Response({'status': membership.status}, status=status.HTTP_201_CREATED)

        status_val = 'pending' if group.requires_approval else 'active'
        is_active_val = (status_val == 'active')
        membership, created = GroupMembership.objects.get_or_create(
            group=group,
            member=profile,
            defaults={
                'status': status_val,
                'is_active': is_active_val
            }
        )
        if not created:
            membership.status = status_val
            membership.is_active = is_active_val
            membership.save()
        if is_active_val:
            # Deactivate others for this user to keep only one active
            GroupMembership.objects.filter(member=profile).exclude(group=group).update(is_active=False)
        return Response({'status': membership.status}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def leave(self, request, pk=None):
        group = self.get_object()
        profile = request.user.profile
        GroupMembership.objects.filter(group=group, member=profile).update(is_active=False, status='inactive')
        return Response({'status': 'left'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def select(self, request, pk=None):
        group = self.get_object()
        profile = request.user.profile
        # Set this one as active in DB (will be used as fallback on web and primary on mobile)
        GroupMembership.objects.filter(member=profile, group=group).update(is_active=True)
        # Deactivate others for this user
        GroupMembership.objects.filter(member=profile).exclude(group=group).update(is_active=False)
        return Response({'status': 'selected'})

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        group = self.get_object()
        profile = request.user.profile
        GroupMembership.objects.filter(group=group, member=profile).update(last_viewed_at=timezone.now())
        return Response({'status': 'marked_read'})

    @action(detail=True, methods=['get'])
    def members(self, request, pk=None):
        group = self.get_object()
        memberships = GroupMembership.objects.filter(group=group, status='active')
        serializer = GroupMembershipSerializer(memberships, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def pending_members(self, request, pk=None):
        group = self.get_object()
        if not group.is_admin(request.user):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        memberships = GroupMembership.objects.filter(group=group, status='pending')
        serializer = GroupMembershipSerializer(memberships, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        group = self.get_object()
        # Transparency: Any active member or admin can view history
        is_member = group.is_member(request.user)
        is_admin = group.is_admin(request.user)
        
        if not (is_member or is_admin):
            return Response(
                {'error': f'Access denied. You must be an active member of {group.name} to view its wallet.'}, 
                status=status.HTTP_403_FORBIDDEN
            )

        transactions = Transaction.objects.filter(
            destination_group=group,
            status='COMPLETED'
        ).order_by('-timestamp')
        
        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def wallet_transfer_requests(self, request, pk=None):
        group = self.get_object()
        if not (group.is_member(request.user) or group.is_admin(request.user)):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

        transfer_requests = GroupWalletTransferRequest.objects.filter(group=group).order_by('-created_at')
        serializer = GroupWalletTransferRequestSerializer(transfer_requests, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def request_wallet_transfer(self, request, pk=None):
        group = self.get_object()
        if not group.is_admin(request.user):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

        recipient_profile_id = request.data.get('recipient_profile')
        amount = request.data.get('amount')
        deceased_contribution_id = request.data.get('deceased_contribution')
        fund_campaign_id = request.data.get('fund_campaign')

        if not recipient_profile_id or amount is None:
            return Response({'error': 'recipient_profile and amount are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            amount_val = Decimal(str(amount))
            if amount_val <= 0:
                raise ValueError()
        except Exception:
            return Response({'error': 'Invalid amount provided.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            recipient_profile = Profile.objects.get(id=recipient_profile_id)
        except Profile.DoesNotExist:
            return Response({'error': 'Recipient member not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not GroupMembership.objects.filter(group=group, member=recipient_profile, status='active', is_active=True).exists():
            return Response({'error': 'Recipient must be an active member of this group.'}, status=status.HTTP_400_BAD_REQUEST)

        if group.get_balance() < amount_val:
            return Response({'error': 'Insufficient group wallet balance for this transfer request.'}, status=status.HTTP_400_BAD_REQUEST)

        from condolence.models import Deceased, FundCampaign
        deceased_contribution = None
        if deceased_contribution_id:
            try:
                deceased_contribution = Deceased.objects.get(id=deceased_contribution_id, group=group)
            except Deceased.DoesNotExist:
                return Response({'error': 'Deceased record not found for this group.'}, status=status.HTTP_404_NOT_FOUND)

        fund_campaign = None
        if fund_campaign_id:
            try:
                fund_campaign = FundCampaign.objects.get(id=fund_campaign_id, group=group)
            except FundCampaign.DoesNotExist:
                return Response({'error': 'Fund campaign not found for this group.'}, status=status.HTTP_404_NOT_FOUND)

        transfer_request = GroupWalletTransferRequest.objects.create(
            group=group,
            requested_by=request.user,
            recipient_profile=recipient_profile,
            amount=amount_val,
            deceased_contribution=deceased_contribution,
            fund_campaign=fund_campaign,
        )

        serializer = GroupWalletTransferRequestSerializer(transfer_request, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def approve_wallet_transfer_request(self, request, pk=None):
        group = self.get_object()
        if not group.is_admin(request.user):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

        transfer_request_id = request.data.get('request_id')
        if not transfer_request_id:
            return Response({'error': 'request_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        transfer_request = get_object_or_404(GroupWalletTransferRequest, id=transfer_request_id, group=group)
        if transfer_request.status != GroupWalletTransferRequest.STATUS_PENDING:
            return Response({'error': 'Transfer request is not pending.'}, status=status.HTTP_400_BAD_REQUEST)

        if transfer_request.approvals.filter(id=request.user.id).exists():
            return Response({'error': 'You have already approved this request.'}, status=status.HTTP_400_BAD_REQUEST)

        transfer_request.approvals.add(request.user)
        transfer_request.save()

        if transfer_request.can_execute():
            try:
                transfer_request.execute()
            except Exception as exc:
                return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = GroupWalletTransferRequestSerializer(transfer_request, context={'request': request})
        return Response(serializer.data)


class OrganisationViewSet(viewsets.ModelViewSet):
    queryset = Organisation.objects.all()
    serializer_class = OrganisationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        profile = self.request.user.profile
        if not profile.is_verified:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only verified users can create Organisations. Please complete your KYC verification first.")
        
        org = serializer.save(creator=self.request.user)
        # Automatically add the creator as admin
        org.admins.add(self.request.user)

    def get_queryset(self):
        queryset = Organisation.objects.filter(is_active=True).order_by('-created_at')
        return queryset

    @action(detail=False, methods=['get'])
    def mine(self, request):
        # Organisations the user created or is an admin of
        orgs = Organisation.objects.filter(
            Q(creator=request.user) | Q(admins=request.user)
        ).distinct().order_by('-created_at')
        serializer = self.get_serializer(orgs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def discover(self, request):
        # Explore active verified organisations
        orgs = Organisation.objects.filter(is_active=True, is_verified=True).order_by('-created_at')
        serializer = self.get_serializer(orgs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='verify-org', permission_classes=[permissions.IsAdminUser])
    def verify_org(self, request, pk=None):
        org = self.get_object()
        is_verified = request.data.get('is_verified', True)
        org.is_verified = bool(is_verified)
        org.save(update_fields=['is_verified'])
        return Response({
            'status': 'updated',
            'organisation_id': org.id,
            'is_verified': org.is_verified
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='request-verification')
    def request_verification(self, request, pk=None):
        org = self.get_object()
        if not org.is_admin(request.user):
            return Response({'error': 'Only organisation admins can request verification.'}, status=status.HTTP_403_FORBIDDEN)
        if org.is_verified:
            return Response({'status': 'already_verified', 'message': 'This organisation is already verified.'})
        return Response({
            'status': 'request_received',
            'message': 'Your verification request has been submitted. The Komunity team will review your organisation within 2–5 business days.'
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        org = self.get_object()
        transactions = Transaction.objects.filter(
            destination_organisation=org,
            status='COMPLETED'
        ).order_by('-timestamp')
        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data)


class GroupMembershipViewSet(viewsets.ModelViewSet):
    queryset = GroupMembership.objects.all()
    serializer_class = GroupMembershipSerializer

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        membership = self.get_object()
        if not membership.group.is_admin(request.user):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        
        membership.approve(request.user)
        
        # Notify the user
        send_push_notification(
            user=membership.member.user,
            title=f"Welcome to {membership.group.name}!",
            message="Your membership request has been approved.",
            notification_type="membership_approved",
            data={'group_id': membership.group.id}
        )
        
        return Response({'status': 'active'})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        membership = self.get_object()
        if not membership.group.is_admin(request.user):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        
        membership.status = 'rejected'
        membership.is_active = False
        membership.save()
        
        # Notify the user
        send_push_notification(
            user=membership.member.user,
            title=f"Membership Update for {membership.group.name}",
            message="Your membership request was declined.",
            notification_type="membership_rejected",
            data={'group_id': membership.group.id}
        )
        
        return Response({'status': 'rejected'})

    @action(detail=True, methods=['post'])
    def declare_deceased(self, request, pk=None):
        membership = self.get_object()
        if not membership.group.is_admin(request.user):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        
        # Update membership status
        membership.is_deceased = True
        membership.is_active = False # No longer an active contributor
        membership.save()
        
        # Create Deceased record in condolence app if it doesn't exist
        deceased_record = Deceased.objects.filter(deceased=membership.member).first()
        if not deceased_record:
            Deceased.objects.create(
                deceased=membership.member,
                group=membership.group,
                group_admin=request.user.profile
            )
        
        # Notify other admins
        admins = membership.group.members.filter(groupmembership__is_admin=True, groupmembership__status='active')
        for admin_profile in admins:
            if admin_profile == request.user.profile: continue # Skip sender
            send_push_notification(
                user=admin_profile.user,
                title="Deceased Member Report",
                message=f"{membership.member.full_name} has been declared deceased in {membership.group.name}.",
                notification_type="deceased_declared",
                data={'group_id': membership.group.id, 'deceased_id': membership.member.id}
            )
            
        return Response({'status': 'deceased_declared'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def change_role(self, request, pk=None):
        membership = self.get_object()
        if not membership.group.is_admin(request.user):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

        new_role = request.data.get('role')
        if new_role not in dict(GroupMembership.ROLE_CHOICES):
            return Response({'error': 'Invalid role'}, status=status.HTTP_400_BAD_REQUEST)

        # Protect the creator's admin role from being downgraded
        if membership.member.user == membership.group.creator and new_role == 'member':
            return Response(
                {'error': 'The group creator cannot be demoted from admin.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        membership.role = new_role
        # Sync is_admin flag for compatibility with older components
        membership.is_admin = new_role in ['admin', 'moderator']
        membership.save()

        return Response({
            'status': 'role updated',
            'role': membership.role,
            'is_admin': membership.is_admin
        })

class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.filter(approved=True).order_by('-created_at')
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination

    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsAuthorOrReadOnly()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        queryset = Post.objects.filter(approved=True).order_by('-created_at')
        
        # Only filter by group_id on list action to avoid 404s on detail/action endpoints
        if self.action == 'list':
            group_id = self.request.query_params.get('group_id')
            if group_id:
                queryset = queryset.filter(group_id=group_id)
            elif self.request.user.is_authenticated:
                # Audit: Default to active group
                active_mem = GroupMembership.objects.filter(
                    member=self.request.user.profile, 
                    is_active=True
                ).first()
                if active_mem:
                    queryset = queryset.filter(group=active_mem.group)
                else:
                    queryset = queryset.none()
        return queryset

    @action(detail=True, methods=['post'])
    def like(self, request, pk=None):
        post = self.get_object()
        try:
            profile = request.user.profile
        except Exception:
            return Response({'error': 'Profile not found'}, status=status.HTTP_400_BAD_REQUEST)
            
        if post.likes.filter(id=profile.id).exists():
            post.likes.remove(profile)
            liked = False
        else:
            post.likes.add(profile)
            liked = True
        return Response({
            'liked': liked,
            'likes_count': post.get_likes_count()
        })

    def perform_create(self, serializer):
        try:
            profile = self.request.user.profile
            post = serializer.save(author=profile)
            
            # Notify group members (limited to 20 for performance)
            if post.group:
                members = post.group.members.filter(groupmembership__status='active').exclude(id=profile.id)[:20]
                for member in members:
                    send_push_notification(
                        user=member.user, # Profile -> User
                        title=f"New Post in {post.group.name}",
                        message=f"{profile.full_name} posted: {post.content[:40]}{'...' if len(post.content) > 40 else ''}",
                        notification_type="new_post",
                        data={'post_id': post.id, 'group_id': post.group.id}
                    )

        except Exception as e:
            # Handle potential missing profile or notification errors
            print(f"Error in post creation/notification: {e}")
            if not serializer.instance: # If save failed before
                 serializer.save()

class PostImageViewSet(viewsets.ModelViewSet):
    queryset = PostImage.objects.all()
    serializer_class = PostImageSerializer
    permission_classes = [permissions.IsAuthenticated, IsPostImageAuthorOrReadOnly]

class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.all().order_by('-created_at')
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrReadOnly]

    def get_queryset(self):
        queryset = Comment.objects.all().order_by('-created_at')
        post_id = self.request.query_params.get('post_id')
        if post_id:
            queryset = queryset.filter(post_id=post_id)
        return queryset

    def perform_create(self, serializer):
        try:
            profile = self.request.user.profile
            serializer.save(author=profile)
        except Exception:
            serializer.save()

class ReplyViewSet(viewsets.ModelViewSet):
    queryset = Reply.objects.all().order_by('created_at')
    serializer_class = ReplySerializer
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrReadOnly]

    def perform_create(self, serializer):
        try:
            profile = self.request.user.profile
            serializer.save(author=profile)
        except Exception:
            serializer.save()

class DeceasedViewSet(viewsets.ModelViewSet):
    queryset = Deceased.objects.filter(cont_is_active=True)
    serializer_class = DeceasedSerializer

    def get_queryset(self):
        queryset = Deceased.objects.filter(cont_is_active=True)
        group_id = self.request.query_params.get('group')
        
        if group_id:
            queryset = queryset.filter(group_id=group_id)
        elif self.request.user.is_authenticated:
            # Fallback to the user's active group
            active_membership = GroupMembership.objects.filter(
                member=self.request.user.profile, 
                is_active=True
            ).first()
            if active_membership:
                queryset = queryset.filter(group=active_membership.group)
            else:
                # If no active group, maybe return empty or all? 
                # For safety in this "filtered" audit, let's return none if they have no active group but are expecting a filtered list
                queryset = queryset.none()
        
        return queryset.order_by('-date')

    @action(detail=True, methods=['post'])
    def disburse_funds(self, request, pk=None):
        deceased = self.get_object()
        if not deceased.group.is_admin(request.user):
            return Response({'error': 'Only group admins can disburse funds'}, status=status.HTTP_403_FORBIDDEN)
        
        if not deceased.beneficiary:
            return Response({'error': 'No beneficiary assigned'}, status=status.HTTP_400_BAD_REQUEST)
        
        balance = deceased.get_balance()
        if balance <= 0:
            return Response({'error': 'No funds available for disbursement'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Perform payout
        from wallet.models import Wallet, Transaction
        from django.db import transaction as db_transaction
        
        # Get or create beneficiary wallet
        beneficiary_wallet, _ = Wallet.objects.get_or_create(
            user=deceased.beneficiary.user, 
            defaults={'external_wallet_id': f"WAAS_{deceased.beneficiary.user.id}"}
        )
        
        with db_transaction.atomic():
            # Create payout transaction for beneficiary
            transaction = Transaction.objects.create(
                wallet=beneficiary_wallet,
                transaction_type='PAYOUT_RECEIVED',
                amount=balance,
                status='COMPLETED',
                destination_group=deceased.group,
                deceased_contribution=deceased,
                waas_reference_id=f"PAY_{timezone.now().timestamp()}"
            )
            beneficiary_wallet.recalculate_balance()
            
            # We no longer close the fund automatically here
            # deceased.funds_disbursed = True
            # deceased.contributions_open = False
            deceased.save()
            
            # Notify beneficiary
            send_push_notification(
                user=deceased.beneficiary.user,
                title="Funds Received",
                message=f"You received {balance} for {deceased.deceased.full_name}.",
                notification_type="funds_disbursed",
                data={'amount': str(balance)}
            )
            
        return Response({
            'status': 'success',
            'amount': balance,
            'beneficiary': deceased.beneficiary.full_name,
            'transaction': TransactionSerializer(transaction).data
        })

class ContributionViewSet(viewsets.ModelViewSet):
    queryset = Contribution.objects.all()
    serializer_class = ContributionSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        queryset = Contribution.objects.filter(contributing_member=self.request.user.profile)
        group_id = self.request.query_params.get('group_id')
        if group_id:
            queryset = queryset.filter(group_id=group_id)
        else:
            active_mem = GroupMembership.objects.filter(
                member=self.request.user.profile, 
                is_active=True
            ).first()
            if active_mem:
                queryset = queryset.filter(group=active_mem.group)
        return queryset.order_by('-contribution_date')

class WalletViewSet(viewsets.ModelViewSet):
    serializer_class = WalletSerializer

    def get_queryset(self):
        return Wallet.objects.filter(user=self.request.user)

    @action(detail=False, methods=['get'])
    def balance(self, request):
        wallet, _ = Wallet.objects.get_or_create(user=request.user, defaults={'external_wallet_id': f"WAAS_{request.user.id}"})
        return Response({'balance': wallet.get_balance()})

    @action(detail=False, methods=['post'])
    def top_up(self, request):
        import uuid
        from wallet.flutterwave import charge_voucher

        wallet, _ = Wallet.objects.get_or_create(
            user=request.user,
            defaults={'external_wallet_id': f"WAAS_{request.user.id}"}
        )
        voucher_pin = request.data.get('voucher_pin')

        if not voucher_pin:
            return Response({'error': 'voucher_pin is required'}, status=status.HTTP_400_BAD_REQUEST)

        # Create a PENDING transaction log entry first
        tx_ref = f"api-topup-{uuid.uuid4().hex[:8]}"
        transaction = Transaction.objects.create(
            wallet=wallet,
            transaction_type='TOP_UP',
            amount=0,
            status='PENDING',
            voucher_reference=voucher_pin,
        )

        # Get phone from user profile if available
        phone = getattr(getattr(request.user, 'profile', None), 'phone', None) or '0000000000'

        user_email = getattr(getattr(request.user, 'profile', None), 'email', 'user@example.com') or 'user@example.com'
        # Call Flutterwave Sandbox
        flw_response = charge_voucher(
            voucher_pin=voucher_pin,
            amount=100.00,   # Sandbox: default 100 ZAR; amount comes back from the voucher
            email=user_email,
            phone_number=phone,
            tx_ref=tx_ref
        )

        if flw_response.get('success'):
            amount_val = flw_response.get('amount', 100.00)
            transaction.status = 'COMPLETED'
            transaction.amount = amount_val
            transaction.waas_reference_id = str(flw_response.get('waas_ref', tx_ref))
            transaction.save()
            wallet.recalculate_balance()
            return Response({
                'status': 'success',
                'balance': str(wallet.get_balance()),
                'transaction': TransactionSerializer(transaction).data
            })
        else:
            transaction.status = 'FAILED'
            transaction.save()
            return Response(
                {'error': flw_response.get('error', 'Voucher redemption failed.')},
                status=status.HTTP_400_BAD_REQUEST
            )


    @action(detail=False, methods=['post'])
    def withdraw(self, request):
        wallet, _ = Wallet.objects.get_or_create(user=request.user, defaults={'external_wallet_id': f"WAAS_{request.user.id}"})
        amount = request.data.get('amount')
        channel = request.data.get('channel')
        metadata = request.data.get('metadata', {}) or {}
        currency = request.data.get('currency', 'ZAR')

        if not amount or not channel:
            return Response({'error': 'Amount and channel are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            amount_val = float(amount)
            if amount_val <= 0:
                return Response({'error': 'Amount must be positive.'}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({'error': 'Invalid amount format.'}, status=status.HTTP_400_BAD_REQUEST)

        if wallet.get_balance() < amount_val:
            return Response({'error': 'Insufficient balance.'}, status=status.HTTP_400_BAD_REQUEST)

        if channel not in [choice.value for choice in Transaction.TransactionChannel]:
            return Response({'error': 'Unsupported payout channel.'}, status=status.HTTP_400_BAD_REQUEST)

        transaction = Transaction.objects.create(
            wallet=wallet,
            transaction_type='WITHDRAWAL',
            amount=amount_val,
            status='PENDING',
            withdrawal_channel=channel,
            withdrawal_metadata={**metadata, 'currency': currency}
        )

        api_response = waas_api_withdraw(wallet.external_wallet_id, channel, metadata, amount_val, currency)
        if api_response['success']:
            transaction.status = 'COMPLETED'
            transaction.waas_reference_id = api_response['waas_ref']
            transaction.save()
            wallet.recalculate_balance()

            return Response({
                'status': 'success',
                'balance': wallet.get_balance(),
                'transaction': TransactionSerializer(transaction).data
            })
        else:
            transaction.status = 'FAILED'
            transaction.save()
            return Response({'error': api_response.get('error', 'Withdrawal failed.')}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def send_money(self, request):
        from django.db import transaction as db_transaction
        
        sender_wallet, _ = Wallet.objects.get_or_create(user=request.user, defaults={'external_wallet_id': f"WAAS_{request.user.id}"})
        recipient_user_id = request.data.get('recipient_user_id')
        amount = request.data.get('amount')
        note = request.data.get('note', '')

        if not recipient_user_id or not amount:
            return Response({'error': 'Recipient and amount are required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            amount_val = float(amount)
            if amount_val <= 0:
                return Response({'error': 'Amount must be positive'}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({'error': 'Invalid amount format'}, status=status.HTTP_400_BAD_REQUEST)

        # Check if sending to self
        if str(request.user.id) == str(recipient_user_id):
            return Response({'error': 'Cannot send money to yourself'}, status=status.HTTP_400_BAD_REQUEST)

        # Get recipient wallet
        try:
            recipient_user = CustomUser.objects.get(id=recipient_user_id)
            recipient_wallet, _ = Wallet.objects.get_or_create(user=recipient_user, defaults={'external_wallet_id': f"WAAS_{recipient_user.id}"})
        except CustomUser.DoesNotExist:
            return Response({'error': 'Recipient not found'}, status=status.HTTP_404_NOT_FOUND)

        # Check balance
        if sender_wallet.get_balance() < amount_val:
            return Response({'error': 'Insufficient balance'}, status=status.HTTP_400_BAD_REQUEST)

        # Create both transactions atomically
        with db_transaction.atomic():
            # Debit from sender
            sender_txn = Transaction.objects.create(
                wallet=sender_wallet,
                transaction_type='P2P_SENT',
                amount=amount,
                status='COMPLETED',
                recipient_wallet=recipient_wallet,
                waas_reference_id=f"P2P_{timezone.now().timestamp()}"
            )

            # Credit to recipient
            recipient_txn = Transaction.objects.create(
                wallet=recipient_wallet,
                transaction_type='P2P_RECEIVED',
                amount=amount,
                status='COMPLETED',
                waas_reference_id=f"P2P_{timezone.now().timestamp()}"
            )
            sender_wallet.recalculate_balance()
            recipient_wallet.recalculate_balance()

        recipient_info = getattr(getattr(recipient_user, 'profile', None), 'email', None) or recipient_user.phone or str(recipient_user.id)
        return Response({
            'status': 'success',
            'balance': sender_wallet.get_balance(),
            'transaction': TransactionSerializer(sender_txn).data,
            'recipient': recipient_info
        })

    @action(detail=False, methods=['post'])
    def contribute_to_deceased(self, request):
        from condolence.models import Deceased, Contribution
        from django.db import transaction as db_transaction
        
        wallet, _ = Wallet.objects.get_or_create(user=request.user, defaults={'external_wallet_id': f"WAAS_{request.user.id}"})
        deceased_id = request.data.get('deceased_id')
        amount = request.data.get('amount')

        if not deceased_id or not amount:
            return Response({'error': 'Deceased member and amount are required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            amount_val = float(amount)
            if amount_val <= 0:
                return Response({'error': 'Amount must be positive'}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({'error': 'Invalid amount format'}, status=status.HTTP_400_BAD_REQUEST)

        # Get deceased member
        try:
            deceased = Deceased.objects.get(id=deceased_id)
        except Deceased.DoesNotExist:
            return Response({'error': 'Deceased member not found'}, status=status.HTTP_404_NOT_FOUND)

        # Check if contributions are still open
        if not deceased.cont_is_active or not deceased.contributions_open:
            return Response({'error': 'Contributions are closed for this member'}, status=status.HTTP_400_BAD_REQUEST)

        # Check balance
        if wallet.get_balance() < amount_val:
            return Response({'error': 'Insufficient balance'}, status=status.HTTP_400_BAD_REQUEST)

        # Create transaction and contribution atomically
        with db_transaction.atomic():
            # Create wallet transaction
            transaction = Transaction.objects.create(
                wallet=wallet,
                transaction_type='TRANSFER',
                amount=amount,
                status='COMPLETED',
                deceased_contribution=deceased,
                waas_reference_id=f"DEC_{timezone.now().timestamp()}"
            )

            # Create contribution record
            contribution = Contribution.objects.create(
                group=deceased.group,
                deceased_member=deceased,
                contributing_member=request.user.profile,
                amount=amount,
                payment_method='wallet',
                transaction=transaction
            )
            wallet.recalculate_balance()

        # Send Notifications
        try:
            # Notify Contributor
            send_push_notification(
                user=request.user,
                title="Contribution Successful",
                message=f"You successfully contributed {amount} to {deceased.deceased.full_name}'s fund.",
                notification_type="contribution_sent",
                data={'contribution_id': contribution.id, 'deceased_id': deceased.id}
            )
            
            # Notify Group Admin
            if deceased.group_admin and deceased.group_admin.user:
                send_push_notification(
                    user=deceased.group_admin.user,
                    title="New Contribution Received",
                    message=f"{request.user.profile.full_name} contributed {amount} to {deceased.deceased.full_name}.",
                    notification_type="contribution_received",
                    data={'contribution_id': contribution.id, 'deceased_id': deceased.id}
                )
        except Exception as e:
            print(f"Error sending contribution notifications: {e}")

        return Response({
            'status': 'success',
            'balance': wallet.get_balance(),
            'transaction': TransactionSerializer(transaction).data,
            'contribution': {
                'id': contribution.id,
                'deceased': deceased.deceased.full_name,
                'amount': str(contribution.amount),
                'total_raised': str(deceased.get_total_raised())
            }
        })

class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TransactionSerializer

    def get_queryset(self):
        return Transaction.objects.filter(wallet__user=self.request.user).order_by('-timestamp')


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_request(request):
    """API endpoint for mobile password reset. Sends a reset email."""
    from django.contrib.auth.forms import PasswordResetForm
    from django.conf import settings

    email = request.data.get('email', '').strip()
    if not email:
        return Response({'error': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

    form = PasswordResetForm(data={'email': email})
    if form.is_valid():
        form.save(
            request=request,
            use_https=request.is_secure(),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@chema101.com'),
            email_template_name='registration/password_reset_email.html',
        )
    # Always return success to avoid revealing which emails exist
    return Response({'detail': 'If an account with that email exists, a password reset link has been sent.'})

from user.models import DeviceToken
from user.serializers import DeviceTokenSerializer

class DeviceTokenViewSet(viewsets.ModelViewSet):
    queryset = DeviceToken.objects.all()
    serializer_class = DeviceTokenSerializer
    # Only authenticated users can register tokens
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return DeviceToken.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        # If token exists for this user, just update updated_at (handled by auto_now)
        # But since token is unique, we might need to handle integrity error or use update_or_create logic manually
        # OR we can let the frontend handle it by checking if it exists?
        # Better: use create to get_or_create.
        pass

    @action(detail=False, methods=['post'])
    def register(self, request):
        token = request.data.get('token')
        platform = request.data.get('platform')
        
        if not token:
            return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        # Update or create
        # Ensure token is unique globally and assigned to current user
        device_token, created = DeviceToken.objects.update_or_create(
            token=token,
            defaults={'user': request.user, 'platform': platform, 'is_active': True}
        )
        
        return Response({'status': 'registered', 'created': created})

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def search_api_view(request):
    """
    Search groups and members.
    Query param: q
    """
    from django.db.models import Q
    query = request.GET.get('q', '').strip()
    
    if not query:
        return Response({'groups': [], 'members': []})

    groups = Group.objects.filter(
        Q(name__icontains=query) | 
        Q(description__icontains=query)
    ).distinct()

    members = Profile.objects.filter(
        Q(user__email__icontains=query) | 
        Q(first_name__icontains=query) | 
        Q(surname__icontains=query)
    ).distinct()

    return Response({
        'groups': GroupSerializer(groups, many=True, context={'request': request}).data,
        'members': ProfileSerializer(members, many=True, context={'request': request}).data
    })


from django.shortcuts import redirect

@api_view(['GET'])
@permission_classes([AllowAny])
def mobile_callback_view(request):
    """
    Callback URL targeted after successful social OAuth redirect on the backend web.
    If authenticated, redirects to the mobile scheme to return the auth token to the app.
    """
    redirect_url = request.GET.get('redirect_url') or "komunity://auth-success"
    if request.user.is_authenticated:
        token, _ = Token.objects.get_or_create(user=request.user)
        separator = "&" if "?" in redirect_url else "?"
        return redirect(f"{redirect_url}{separator}token={token.key}")
    
    failure_url = request.GET.get('failure_url') or "komunity://auth-failed"
    return redirect(failure_url)


# =============================================================================
# FundCampaign ViewSet
# =============================================================================

from condolence.models import FundCampaign, CampaignContribution
from condolence.serializers import FundCampaignSerializer, CampaignContributionSerializer

class FundCampaignViewSet(viewsets.ModelViewSet):
    """
    CRUD for FundCampaign objects.

    Endpoints:
      GET    /api/v1/campaigns/                 - list campaigns for active/requested group
      GET    /api/v1/campaigns/public/          - list all public (emergency) campaigns
      POST   /api/v1/campaigns/                 - create a new campaign (admin only)
      GET    /api/v1/campaigns/{id}/            - retrieve campaign detail
      PATCH  /api/v1/campaigns/{id}/            - update campaign (admin only)
      POST   /api/v1/campaigns/{id}/contribute/ - contribute from wallet balance
      POST   /api/v1/campaigns/{id}/disburse/   - disburse funds to beneficiary (admin)
      POST   /api/v1/campaigns/{id}/close/      - close campaign (admin)
    """
    queryset = FundCampaign.objects.all()
    serializer_class = FundCampaignSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = FundCampaign.objects.all()
        group_id = self.request.query_params.get('group')
        organisation_id = self.request.query_params.get('organisation')
        if group_id:
            queryset = queryset.filter(group_id=group_id)
        elif organisation_id:
            queryset = queryset.filter(organisation_id=organisation_id)
        elif self.action == 'list':
            # Default: campaigns for the user's active group
            active_mem = GroupMembership.objects.filter(
                member=self.request.user.profile, is_active=True
            ).first()
            if active_mem:
                queryset = queryset.filter(group=active_mem.group)
            else:
                queryset = queryset.none()
        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        group = serializer.validated_data.get('group')
        organisation = serializer.validated_data.get('organisation')
        
        if group:
            if not group.is_admin(self.request.user):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("Only group admins can create fund campaigns.")
        elif organisation:
            if not organisation.is_admin(self.request.user):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("Only organisation admins can create fund campaigns.")
        else:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("A campaign must be linked to either a Group or an Organisation.")

        # Emergency campaigns are always public
        campaign_type = serializer.validated_data.get('campaign_type', 'custom')
        is_public = (campaign_type == 'emergency')
        serializer.save(created_by=self.request.user.profile, is_public=is_public)

    # ── Public fundraisers list (no auth filter) ─────────────────────────────
    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def public(self, request):
        """Returns all active public (emergency) campaigns visible to any user."""
        campaigns = FundCampaign.objects.filter(
            is_public=True,
            contributions_open=True,
            organisation__is_verified=True,
        ).select_related('organisation', 'beneficiary', 'created_by').order_by('-created_at')
        serializer = self.get_serializer(campaigns, many=True)
        return Response(serializer.data)

    # ── Contribute from wallet ────────────────────────────────────────────────
    @action(detail=True, methods=['post'])
    def contribute(self, request, pk=None):
        """Deduct from user wallet and log a CampaignContribution."""
        campaign = self.get_object()
        if not campaign.contributions_open:
            return Response({'error': 'This campaign is no longer accepting contributions.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from decimal import Decimal
            amount = Decimal(str(request.data.get('amount', 0)))
            if amount <= 0:
                raise ValueError("Amount must be positive")
        except Exception:
            return Response({'error': 'Invalid amount.'}, status=status.HTTP_400_BAD_REQUEST)

        profile = request.user.profile

        # Prevent duplicate contribution
        if CampaignContribution.objects.filter(campaign=campaign, contributing_member=profile).exists():
            return Response({'error': 'You have already contributed to this campaign.'}, status=status.HTTP_400_BAD_REQUEST)

        from wallet.models import Wallet, Transaction as WalletTransaction
        from django.db import transaction as db_transaction

        wallet, _ = Wallet.objects.get_or_create(
            user=request.user,
            defaults={'external_wallet_id': f"WAAS_{request.user.id}"}
        )

        if wallet.get_balance() < amount:
            return Response({'error': 'Insufficient wallet balance.'}, status=status.HTTP_400_BAD_REQUEST)

        note = request.data.get('note', '')

        with db_transaction.atomic():
            tx = WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type='TRANSFER',
                amount=amount,
                status='COMPLETED',
                destination_group=campaign.group,
                destination_organisation=campaign.organisation,
                fund_campaign=campaign,
                waas_reference_id=f"CAMP_{timezone.now().timestamp()}"
            )
            contribution = CampaignContribution.objects.create(
                campaign=campaign,
                group=campaign.group,
                organisation=campaign.organisation,
                contributing_member=profile,
                amount=amount,
                payment_method='wallet',
                transaction=tx,
                note=note,
            )
            wallet.recalculate_balance()

        # Notify campaign admin
        admin_user = campaign.created_by.user if campaign.created_by else (campaign.group.creator if campaign.group else campaign.organisation.creator)
        notification_data = {'campaign_id': campaign.id}
        if campaign.group:
            notification_data['group_id'] = campaign.group.id
        elif campaign.organisation:
            notification_data['organisation_id'] = campaign.organisation.id

        send_push_notification(
            user=admin_user,
            title=f"New Contribution to {campaign.title}",
            message=f"{profile.full_name} contributed R{amount} to '{campaign.title}'.",
            notification_type="campaign_contribution",
            data=notification_data
        )

        return Response({
            'status': 'success',
            'amount': str(amount),
            'total_raised': float(campaign.get_total_raised()),
            'contributor_count': campaign.get_contributor_count(),
        }, status=status.HTTP_201_CREATED)

    # ── Disburse funds to beneficiary ─────────────────────────────────────────
    @action(detail=True, methods=['post'])
    def disburse(self, request, pk=None):
        """Transfer the collected balance to the beneficiary's wallet (admin only)."""
        campaign = self.get_object()
        is_admin = campaign.group.is_admin(request.user) if campaign.group else campaign.organisation.is_admin(request.user)
        if not is_admin:
            return Response({'error': 'Only admins can disburse funds.'}, status=status.HTTP_403_FORBIDDEN)
        if not campaign.beneficiary:
            return Response({'error': 'No beneficiary assigned to this campaign.'}, status=status.HTTP_400_BAD_REQUEST)

        balance = campaign.get_balance()
        if balance <= 0:
            return Response({'error': 'No funds available for disbursement.'}, status=status.HTTP_400_BAD_REQUEST)

        from wallet.models import Wallet, Transaction as WalletTransaction
        from django.db import transaction as db_transaction

        beneficiary_wallet, _ = Wallet.objects.get_or_create(
            user=campaign.beneficiary.user,
            defaults={'external_wallet_id': f"WAAS_{campaign.beneficiary.user.id}"}
        )

        with db_transaction.atomic():
            tx = WalletTransaction.objects.create(
                wallet=beneficiary_wallet,
                transaction_type='PAYOUT_RECEIVED',
                amount=balance,
                status='COMPLETED',
                destination_group=campaign.group,
                destination_organisation=campaign.organisation,
                fund_campaign=campaign,
                waas_reference_id=f"PAY_CAMP_{timezone.now().timestamp()}"
            )
            beneficiary_wallet.recalculate_balance()
            campaign.funds_disbursed = True
            campaign.save()

        send_push_notification(
            user=campaign.beneficiary.user,
            title="Campaign Funds Received",
            message=f"You received R{balance} from the '{campaign.title}' campaign.",
            notification_type="campaign_disbursed",
            data={'amount': str(balance), 'campaign_id': campaign.id}
        )

        return Response({
            'status': 'success',
            'amount_disbursed': str(balance),
            'beneficiary': campaign.beneficiary.full_name,
        })

    # ── Close campaign ────────────────────────────────────────────────────────
    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """Close the campaign to new contributions (admin only)."""
        campaign = self.get_object()
        is_admin = campaign.group.is_admin(request.user) if campaign.group else campaign.organisation.is_admin(request.user)
        if not is_admin:
            return Response({'error': 'Only admins can close a campaign.'}, status=status.HTTP_403_FORBIDDEN)
        campaign.close()
        return Response({'status': 'closed', 'contributions_open': False})
