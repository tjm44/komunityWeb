import os
import random
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from user.models import Profile

class Group(models.Model):

    GROUP_PURPOSE_CHOICES = [
        ('bereavement', 'Bereavement Fund'),
        ('excess', 'Insurance Excess Fund'),
        ('emergency', 'Emergency / Disaster Fundraiser'),
        ('custom', 'Custom Fund'),
    ]

    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    description = models.TextField(null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    cover_image = models.ImageField(upload_to='group_cover_images', null=True, blank=True)
    admin = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True, related_name='admin_groups')
    members = models.ManyToManyField(Profile, through='GroupMembership', related_name='groups')
    
    max_members = models.PositiveIntegerField(null=True, blank=True, help_text="Leave blank for unlimited")
    requires_approval = models.BooleanField(default=False, help_text="New members need approval")
    
    # Ownership
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_groups',null=True, blank=True)
    admins  = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='admin_groups', blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True,null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Group Purpose & Fund Type
    purpose = models.CharField(
        max_length=20,
        choices=GROUP_PURPOSE_CHOICES,
        default='bereavement',
        help_text="The primary fund-pooling purpose of this group"
    )
    fund_description = models.TextField(
        null=True, blank=True,
        help_text="Detailed description of the group's fund purpose (used for 'custom' and 'emergency' types)"
    )
    verified_members_only = models.BooleanField(
        default=False,
        help_text="Only allow verified user profiles to join this group"
    )

    # Wallet Integration
    external_wallet_id = models.CharField(max_length=100, unique=True, null=True, blank=True)

    def get_admins(self):
        return self.members.filter(groupmembership__is_admin=True)
    
    def get_total_members(self):
        return self.groupmembership_set.filter(status='active').count()

    def get_active_members(self):
        return self.members.filter(groupmembership__status='active')


    def get_balance(self):
        from wallet.models import Transaction
        from django.db.models import Sum
        from decimal import Decimal
        
        # Incoming: Transfers from members
        incoming = Transaction.objects.filter(
            destination_group=self,
            transaction_type='TRANSFER',
            status='COMPLETED'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Outgoing: Payouts/Disbursements to members
        outgoing = Transaction.objects.filter(
            destination_group=self,
            transaction_type='PAYOUT_RECEIVED',
            status='COMPLETED'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        return incoming - outgoing

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('create_post', args=[str(self.id)])

    def is_admin(self, user):
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        # Creator check
        if user == self.creator:
            return True
        # Admins M2M check
        if user in self.admins.all():
            return True
        # Membership role check
        return self.groupmembership_set.filter(
            member__user=user, 
            role__in=['admin', 'moderator'],
            is_active=True
        ).exists()

    def is_member(self, user):
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        try:
            profile = user.profile
        except Exception:
            return False
            
        return self.groupmembership_set.filter(
            member=profile, 
            status='active',
            is_active=True
        ).exists()


    def can_join(self, user):
        """Check if user can join this group"""
        if not user.is_authenticated:
            return False, "You must be logged in to join groups"
        
        if self.is_member(user):
            return False, "You're already a member of this group"
        
        if self.privacy == 'closed':
            return False, "This group is closed to new members"
        
        if self.is_full:
            return False, "This group has reached its maximum capacity"
        
        return True, "Can join"    
    
    def save(self, *args, **kwargs):
        if not self.pk and not self.cover_image:  # Only if it's a new group and no cover image is provided
            try:
                # Try to find default images in STATIC_ROOT first, then project's static folder
                possible_dirs = [
                    os.path.join(settings.BASE_DIR, 'static', 'group_cover_images'),
                    os.path.join(settings.STATIC_ROOT, 'group_cover_images') if hasattr(settings, 'STATIC_ROOT') and settings.STATIC_ROOT else None
                ]
                
                for cover_images_dir in possible_dirs:
                    if cover_images_dir and os.path.exists(cover_images_dir):
                        cover_images = [os.path.join('group_cover_images', file) for file in os.listdir(cover_images_dir) if file.endswith(('.jpg', '.jpeg', '.png', '.gif'))]
                        if cover_images:
                            self.cover_image = random.choice(cover_images)
                            break
            except Exception as e:
                print(f"Error setting default cover image: {e}")
                
        super().save(*args, **kwargs)


class Organisation(models.Model):
    ENTITY_TYPE_CHOICES = [
        ('ngo', 'NGO'),
        ('church', 'Church/Religious Org'),
        ('npo', 'NPO/Charity'),
        ('corporate', 'Corporate/Business'),
        ('other', 'Other Organisation'),
    ]

    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    description = models.TextField(null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    cover_image = models.ImageField(upload_to='organisation_cover_images', null=True, blank=True)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_organisations', null=True, blank=True)
    admins  = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='admin_organisations', blank=True)
    admin2 = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='admin2_organisations', null=True, blank=True)
    admin3 = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='admin3_organisations', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Legal / verification details
    is_verified = models.BooleanField(default=False)
    registration_number = models.CharField(max_length=100, blank=True, null=True)
    entity_type = models.CharField(max_length=50, choices=ENTITY_TYPE_CHOICES, default='ngo')

    # Wallet
    external_wallet_id = models.CharField(max_length=100, unique=True, null=True, blank=True)

    def get_balance(self):
        from wallet.models import Transaction
        from django.db.models import Sum
        from decimal import Decimal
        incoming = Transaction.objects.filter(
            destination_organisation=self,
            transaction_type='TRANSFER',
            status='COMPLETED'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        outgoing = Transaction.objects.filter(
            destination_organisation=self,
            transaction_type='PAYOUT_RECEIVED',
            status='COMPLETED'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        return incoming - outgoing

    def __str__(self):
        return self.name

    def is_admin(self, user):
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if user == self.creator:
            return True
        if user in self.admins.all():
            return True
        if user == self.admin2 or user == self.admin3:
            return True
        return False




class GroupMembership(models.Model):

    ROLE_CHOICES = [
        ('member', 'Member'),
        ('moderator', 'Moderator'),
        ('admin', 'Admin'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('banned', 'Banned'),
    ]
    member      = models.ForeignKey(Profile, on_delete=models.CASCADE)
    group       = models.ForeignKey(Group, on_delete=models.CASCADE)
    is_admin    = models.BooleanField(default=False)
    status   = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    role     = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')
    date_joined = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey( settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,blank=True,related_name='approved_memberships')
    is_active   = models.BooleanField(default=True)
    is_deceased = models.BooleanField(default=False)
    can_post    = models.BooleanField(default=True)
    can_comment = models.BooleanField(default=True)
    join_message = models.TextField(blank=True, help_text="Message when requesting to join")
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.member.full_name} in {self.group.name}"
    
    def get_is_admin(self):
        return self.is_admin

    def approve(self, approved_by_user):
        """Approve membership"""
        self.status = 'active'
        self.is_active = True
        self.approved_at = timezone.now()
        self.approved_by = approved_by_user
        self.save()

    def is_admin_or_creator(self):
        return (self.role in ['admin', 'moderator'] or 
                self.user == self.group.creator)    


class Post(models.Model):
    author = models.ForeignKey(Profile, on_delete=models.CASCADE, null=True, blank=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, null=True, blank=True)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, null=True, blank=True, related_name='posts')
    content = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='post_images/', null=True, blank=True)
    video = models.FileField(upload_to='post_videos/', null=True, blank=True)
    likes = models.ManyToManyField(Profile, related_name='liked_posts', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    approved = models.BooleanField(default=True, null=True, blank=True)

    def __str__(self):
        return f"{self.author.full_name}: {self.content}"

    def get_likes_count(self):
        return self.likes.count()



class PostImage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='post_images/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Image for {self.post.id}"
    
    class Meta:
        ordering = ['uploaded_at']


class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE)
    author = models.ForeignKey(Profile, on_delete=models.CASCADE, null=True, blank=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.author.full_name}: {self.content}"

    class Meta:
        ordering = ['-created_at']


class Reply(models.Model):
    author = models.ForeignKey(Profile, on_delete=models.CASCADE, null=True, blank=True)
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='replies', null=True, blank=True)
    content = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    def __str__(self):
        return f'Reply by {self.author.full_name} -> {self.content}'

    class Meta:
        verbose_name_plural = "Replies"
        ordering = ['created_at']
        
class Dependent(models.Model):
    guardian = models.ForeignKey(Profile, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100,null=True, blank=True)
    date_of_birth = models.DateField()
    relationship = models.CharField(max_length=100, null=True, blank=True)
    date_added = models.DateTimeField(auto_now_add=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='dependents',null=True, blank=True)

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────────────────────
# Signal: enforce creator admin membership on every Group save
# ─────────────────────────────────────────────────────────────

@receiver(post_save, sender=Group)
def ensure_creator_is_admin(sender, instance, created, **kwargs):
    """
    Whenever a Group is saved, guarantee the creator has an active admin
    GroupMembership.  This is the single source of truth so that the rule
    is enforced regardless of which code path creates or edits the group.
    """
    if not instance.creator:
        return

    try:
        creator_profile = instance.creator.profile
    except Exception:
        return

    membership, _ = GroupMembership.objects.get_or_create(
        group=instance,
        member=creator_profile,
        defaults={
            'is_admin': True,
            'role': 'admin',
            'status': 'active',
            'is_active': True,
        }
    )

    # Repair any existing membership that lost admin rights
    needs_save = False
    if not membership.is_admin:
        membership.is_admin = True
        needs_save = True
    if membership.role not in ('admin', 'moderator'):
        membership.role = 'admin'
        needs_save = True
    if membership.status != 'active':
        membership.status = 'active'
        needs_save = True
    if not membership.is_active:
        membership.is_active = True
        needs_save = True
    if needs_save:
        membership.save()
