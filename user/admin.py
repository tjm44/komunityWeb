from django.contrib import admin
from .models import Profile, CustomUser, DeviceToken, Notification, PhoneOTP


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'user_phone', 'email', 'phone', 'is_email_verified', 'is_verified', 'is_active', 'is_complete', 'created_at')
    search_fields = ('first_name', 'surname', 'email', 'phone', 'user__phone')
    list_filter = ('is_verified', 'is_email_verified', 'is_active', 'is_complete', 'is_deceased')
    readonly_fields = ('created_at', 'updated_at')

    def full_name(self, obj):
        return obj.full_name
    full_name.short_description = 'Full Name'

    def user_phone(self, obj):
        return obj.user.phone or f"User #{obj.user.id}"
    user_phone.short_description = 'Phone (Auth)'


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ('phone', 'pin_set', 'is_phone_verified', 'is_staff', 'is_active', 'date_joined')
    search_fields = ('phone',)
    list_filter = ('is_phone_verified', 'is_staff', 'is_active', 'date_joined')
    readonly_fields = ('date_joined', 'last_login')

    def pin_set(self, obj):
        return obj.has_pin
    pin_set.boolean = True
    pin_set.short_description = 'PIN Configured'


@admin.register(PhoneOTP)
class PhoneOTPAdmin(admin.ModelAdmin):
    list_display = ('phone', 'otp', 'is_verified', 'attempts', 'is_valid_status', 'created_at', 'expires_at')
    search_fields = ('phone', 'otp')
    list_filter = ('is_verified', 'created_at')
    readonly_fields = ('created_at',)

    def is_valid_status(self, obj):
        return obj.is_valid()
    is_valid_status.boolean = True
    is_valid_status.short_description = 'Valid & Active'


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'platform', 'is_active', 'created_at')
    search_fields = ('user__phone', 'token')
    list_filter = ('platform', 'is_active', 'created_at')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'title', 'notification_type', 'is_read', 'created_at')
    search_fields = ('recipient__phone', 'title', 'message')
    list_filter = ('is_read', 'notification_type', 'created_at')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)
