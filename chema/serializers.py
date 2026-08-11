from rest_framework import serializers
from .models import Group, GroupMembership, Post, PostImage, Comment, Reply, Dependent, Organisation
from user.serializers import ProfileSerializer

class GroupMembershipSerializer(serializers.ModelSerializer):
    member_detail = ProfileSerializer(source='member', read_only=True)

    class Meta:
        model = GroupMembership
        fields = [
            'id', 'member', 'member_detail', 'group', 'is_admin', 
            'status', 'role', 'date_joined', 'is_active', 'is_deceased'
        ]

class GroupSerializer(serializers.ModelSerializer):
    total_members = serializers.IntegerField(source='get_total_members', read_only=True)
    balance = serializers.DecimalField(source='get_balance', max_digits=10, decimal_places=2, read_only=True)
    is_admin = serializers.SerializerMethodField()
    is_selected = serializers.SerializerMethodField()
    unread_posts_count = serializers.SerializerMethodField()
    membership_status = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            'id', 'name', 'is_active', 'description', 'cover_image', 
            'total_members', 'requires_approval', 'created_at', 'is_admin', 'balance',
            'is_selected', 'unread_posts_count', 'membership_status',
            # Fund purpose fields
            'purpose', 'fund_description', 'verified_members_only',
            # Notification settings
            'notify_on_member_join', 'notify_on_member_promote', 
            'notify_on_wallet_transfer', 'notify_on_campaign_created',
            # Governance
            'min_disbursement_approvals',
        ]

    def get_is_selected(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                membership = GroupMembership.objects.filter(group=obj, member=request.user.profile).first()
                return membership.is_active if membership else False
            except Exception:
                return False
        return False

    def get_is_admin(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.is_admin(request.user)
        return False

    def get_unread_posts_count(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                membership = GroupMembership.objects.filter(group=obj, member=request.user.profile).first()
                if not membership:
                    return 0
                
                query = Post.objects.filter(group=obj, approved=True)
                if membership.last_viewed_at:
                    query = query.filter(created_at__gt=membership.last_viewed_at)
                
                # Exclude own posts from unread count
                query = query.exclude(author=request.user.profile)
                
                return query.count()
            except Exception:
                return 0
        return 0

    def get_membership_status(self, obj):
        """Returns 'active', 'pending', or null if user is not a member."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                membership = GroupMembership.objects.filter(group=obj, member=request.user.profile).first()
                if membership:
                    return membership.status
            except Exception:
                pass
        return None

class OrganisationSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(source='get_balance', max_digits=10, decimal_places=2, read_only=True)
    is_admin = serializers.SerializerMethodField()
    admin2_detail = ProfileSerializer(source='admin2.profile', read_only=True)
    admin3_detail = ProfileSerializer(source='admin3.profile', read_only=True)

    class Meta:
        model = Organisation
        fields = [
            'id', 'name', 'is_active', 'description', 'cover_image',
            'created_at', 'is_admin', 'balance',
            # Registry fields
            'is_verified', 'registration_number', 'entity_type',
            'email', 'phone_number', 'admin2', 'admin3',
            'admin2_detail', 'admin3_detail',
        ]

    def get_is_admin(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.is_admin(request.user)
        return False

class PostImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostImage
        fields = ['id', 'post', 'image', 'uploaded_at']

from chema.models import Comment

class ReplySerializer(serializers.ModelSerializer):
    author_detail = ProfileSerializer(source='author', read_only=True)
    comment = serializers.PrimaryKeyRelatedField(queryset=Comment.objects.all())

    class Meta:
        model = Reply
        fields = ['id', 'author', 'author_detail', 'content', 'created_at', 'comment']
        read_only_fields = ['author', 'created_at']

class CommentSerializer(serializers.ModelSerializer):
    author_detail = ProfileSerializer(source='author', read_only=True)
    replies = ReplySerializer(many=True, read_only=True)

    class Meta:
        model = Comment
        fields = ['id', 'post', 'author', 'author_detail', 'content', 'created_at', 'replies']
        read_only_fields = ['author']

class PostSerializer(serializers.ModelSerializer):
    author_detail = ProfileSerializer(source='author', read_only=True)
    images = PostImageSerializer(many=True, read_only=True)
    comment_count = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    has_liked = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'author', 'author_detail', 'group', 'organisation', 'content', 
            'images', 'video', 'created_at', 'approved', 'comment_count',
            'likes_count', 'has_liked'
        ]
        read_only_fields = ['author']

    def get_comment_count(self, obj):
        return Comment.objects.filter(post=obj).count()

    def get_likes_count(self, obj):
        return obj.get_likes_count()

    def get_has_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                profile = request.user.profile
                return obj.likes.filter(id=profile.id).exists()
            except Exception:
                return False
        return False

class DependentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dependent
        fields = [
            'id', 'guardian', 'name', 'date_of_birth', 
            'relationship', 'group'
        ]
