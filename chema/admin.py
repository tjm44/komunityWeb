from django.contrib import admin
from .models import Group, Organisation, GroupMembership, Post, PostImage, Comment, Reply, Dependent


# ─────────────────────────────────────────────────────────────
#  Inline classes for nested editing
# ─────────────────────────────────────────────────────────────

class GroupMembershipInline(admin.TabularInline):
    model = GroupMembership
    extra = 0
    fields = ('member', 'role', 'status', 'is_admin', 'is_active', 'date_joined')
    readonly_fields = ('date_joined',)
    raw_id_fields = ('member',)


class PostImageInline(admin.TabularInline):
    model = PostImage
    extra = 0
    readonly_fields = ('uploaded_at',)


# ─────────────────────────────────────────────────────────────
#  Group
# ─────────────────────────────────────────────────────────────

@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'purpose', 'creator', 'total_members', 'group_balance', 'is_active', 'created_at')
    search_fields = ('name', 'creator__email', 'description')
    list_filter = ('purpose', 'is_active', 'requires_approval', 'verified_members_only', 'created_at')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('admin', 'creator')
    inlines = [GroupMembershipInline]
    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'description', 'cover_image', 'is_active')
        }),
        ('Purpose & Fund Type', {
            'fields': ('purpose', 'fund_description')
        }),
        ('Ownership', {
            'fields': ('creator', 'admin', 'admins')
        }),
        ('Settings', {
            'fields': ('max_members', 'requires_approval', 'verified_members_only')
        }),
        ('Wallet Integration', {
            'fields': ('external_wallet_id',),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def total_members(self, obj):
        return obj.get_total_members()
    total_members.short_description = 'Members'

    def group_balance(self, obj):
        return f"R {obj.get_balance()}"
    group_balance.short_description = 'Balance'


# ─────────────────────────────────────────────────────────────
#  Organisation
# ─────────────────────────────────────────────────────────────

@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ('name', 'entity_type', 'is_verified', 'is_active', 'creator', 'created_at')
    search_fields = ('name', 'description', 'registration_number', 'creator__email', 'email', 'phone_number')
    list_filter = ('entity_type', 'is_verified', 'is_active', 'created_at')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('creator', 'admin2', 'admin3')
    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'description', 'cover_image', 'is_active')
        }),
        ('Contact Info', {
            'fields': ('email', 'phone_number')
        }),
        ('Legal Details', {
            'fields': ('entity_type', 'registration_number', 'is_verified')
        }),
        ('Ownership', {
            'fields': ('creator', 'admins', 'admin2', 'admin3')
        }),
        ('Wallet', {
            'fields': ('external_wallet_id',),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


# ─────────────────────────────────────────────────────────────
#  GroupMembership
# ─────────────────────────────────────────────────────────────

@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ('member', 'group', 'role', 'status', 'is_admin', 'is_active', 'is_deceased', 'date_joined')
    search_fields = ('member__first_name', 'member__surname', 'group__name')
    list_filter = ('role', 'status', 'is_admin', 'is_active', 'is_deceased', 'date_joined')
    date_hierarchy = 'date_joined'
    readonly_fields = ('date_joined', 'approved_at')
    raw_id_fields = ('member', 'group', 'approved_by')


# ─────────────────────────────────────────────────────────────
#  Post
# ─────────────────────────────────────────────────────────────

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('author', 'group', 'organisation', 'approved', 'created_at', 'likes_count')
    search_fields = ('content', 'author__first_name', 'author__surname', 'group__name')
    list_filter = ('approved', 'created_at', 'group')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)
    raw_id_fields = ('author', 'group', 'organisation')
    inlines = [PostImageInline]

    def likes_count(self, obj):
        return obj.likes.count()
    likes_count.short_description = 'Likes'


# ─────────────────────────────────────────────────────────────
#  Comment
# ─────────────────────────────────────────────────────────────

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('author', 'post', 'short_content', 'created_at')
    search_fields = ('content', 'author__first_name', 'author__surname')
    list_filter = ('created_at',)
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)
    raw_id_fields = ('author', 'post')

    def short_content(self, obj):
        return obj.content[:60] + ('…' if len(obj.content) > 60 else '')
    short_content.short_description = 'Content'


# ─────────────────────────────────────────────────────────────
#  Reply
# ─────────────────────────────────────────────────────────────

@admin.register(Reply)
class ReplyAdmin(admin.ModelAdmin):
    list_display = ('author', 'comment', 'short_content', 'created_at')
    search_fields = ('content', 'author__first_name', 'author__surname')
    list_filter = ('created_at',)
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)
    raw_id_fields = ('author', 'comment')

    def short_content(self, obj):
        return (obj.content or '')[:60] + ('…' if obj.content and len(obj.content) > 60 else '')
    short_content.short_description = 'Content'


# ─────────────────────────────────────────────────────────────
#  Dependent
# ─────────────────────────────────────────────────────────────

@admin.register(Dependent)
class DependentAdmin(admin.ModelAdmin):
    list_display = ('name', 'guardian', 'relationship', 'date_of_birth', 'group', 'date_added')
    search_fields = ('name', 'guardian__first_name', 'guardian__surname', 'relationship')
    list_filter = ('relationship', 'date_added', 'group')
    readonly_fields = ('date_added',)
    raw_id_fields = ('guardian', 'group')


