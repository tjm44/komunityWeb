from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import Wallet
from chema.models import Group

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_wallet(sender, instance, created, **kwargs):
    if created:
        new_external_id = f"auto_{instance.phone or instance.id}" 
        Wallet.objects.get_or_create(user=instance, defaults={'external_wallet_id': new_external_id})

@receiver(post_save, sender=Group)
def create_group_wallet_id(sender, instance, created, **kwargs):
    if not instance.external_wallet_id:
        instance.external_wallet_id = f"group_wallet_{instance.id}_{instance.name[:20].replace(' ', '_')}"
        # We use update to avoid triggering post_save again in an infinite loop
        Group.objects.filter(pk=instance.pk).update(external_wallet_id=instance.external_wallet_id)
