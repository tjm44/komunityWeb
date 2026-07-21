# models.py in the condolences app
from django.db import models
from django.contrib.auth.models import User
from django.apps import apps
from chema.models import *
from user.models import Profile


class Contribution(models.Model):
    group           = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='group_contributions')
    deceased_member = models.ForeignKey('Deceased', on_delete=models.CASCADE, related_name='member_deceased', null=True, blank=True)
    contributing_member = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='deceased_contributions', null=True, blank=True)
    group_admin = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='admin_contributions', null=True, blank=True)
    amount      = models.DecimalField(default=100.00, max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=50, default='cash', choices=[
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('mobile_money', 'Mobile Money'),
        ('wallet', 'Wallet Balance'),
        ('other', 'Other'),
    ])
    transaction = models.ForeignKey('wallet.Transaction', on_delete=models.SET_NULL, null=True, blank=True, related_name='contribution')
    contribution_date = models.DateField(auto_now_add=True)
    
    def __str__(self):
        return f"Contribution by {self.contributing_member} on {self.contribution_date} in {self.group.name} for{self.deceased_member}"
    
    class Meta:
        unique_together = ('deceased_member', 'contributing_member')
    
class Deceased(models.Model):
    deceased  = models.OneToOneField(Profile, on_delete=models.CASCADE,related_name='profile_deceased',default=True, unique=True)
    group     = models.ForeignKey(Group, on_delete=models.CASCADE)
    date      = models.DateField(auto_now_add=True)
    group_admin = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True, related_name='admin')
    contributions_open = models.BooleanField(default=True)
    cont_is_active = models.BooleanField(default=True)
    
    # Beneficiary & Payout
    beneficiary = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True, related_name='beneficiary_for')
    funds_disbursed = models.BooleanField(default=False)

    def __str__ (self):
       return f"{self.deceased}"
   
    def stop_contributions(self):
        self.cont_is_active = False
        self.contributions_open = False
        self.save()

    def get_total_raised(self):
        from django.db.models import Sum
        return self.member_deceased.aggregate(total=Sum('amount'))['total'] or 0

    def get_total_disbursed(self):
        from django.db.models import Sum
        # Sum of all payout transactions linked to this deceased member
        return self.wallet_contributions.filter(
            transaction_type='PAYOUT_RECEIVED', 
            status='COMPLETED'
        ).aggregate(total=Sum('amount'))['total'] or 0

    def get_balance(self):
        # Balance held by group for this deceased member (Raised - Disbursed)
        from decimal import Decimal
        raised = self.get_total_raised()
        disbursed = self.get_total_disbursed()
        return raised - disbursed


# ---------------------------------------------------------------------------
# Generic Fund Campaign  (Excess, Emergency, Custom)
# ---------------------------------------------------------------------------

class FundCampaign(models.Model):
    """
    A flexible fund-pooling campaign for any group purpose type.

    Excess:     linked to a claimant member (mirrors Deceased -> Profile).
    Emergency:  is_public=True; only allowed for is_verified (NGO/Church) groups.
    Custom:     open-ended collection with optional target.
    """

    CAMPAIGN_TYPE_CHOICES = [
        ('bereavement', 'Bereavement'),
        ('excess', 'Insurance Excess'),
        ('emergency', 'Emergency / Disaster'),
        ('custom', 'Custom'),
    ]

    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name='fund_campaigns', null=True, blank=True
    )
    organisation = models.ForeignKey(
        'chema.Organisation', on_delete=models.CASCADE, related_name='fund_campaigns', null=True, blank=True
    )
    campaign_type = models.CharField(
        max_length=20, choices=CAMPAIGN_TYPE_CHOICES, default='custom'
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # The beneficiary / claimant (required for 'excess' and 'bereavement')
    beneficiary = models.ForeignKey(
        Profile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='beneficiary_campaigns'
    )

    # Optional fundraising goal — any amount is accepted regardless
    target_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Optional goal. Leave blank for open-ended collection."
    )

    contributions_open = models.BooleanField(default=True)
    funds_disbursed = models.BooleanField(default=False)

    # Emergency campaigns are public: visible to all users in the Fundraisers tab
    is_public = models.BooleanField(
        default=False,
        help_text="Public campaigns appear in the global Fundraisers tab for all users."
    )

    created_by = models.ForeignKey(
        Profile, on_delete=models.SET_NULL, null=True,
        related_name='created_campaigns'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    deadline = models.DateField(
        null=True, blank=True,
        help_text="Optional end date. Contributions close after this date."
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        group_name = self.group.name if self.group else "No Group"
        return f"{self.get_campaign_type_display()} – {self.title} ({group_name})"

    def get_total_raised(self):
        from django.db.models import Sum
        return self.campaign_contributions.aggregate(
            total=Sum('amount')
        )['total'] or 0

    def get_contributor_count(self):
        return self.campaign_contributions.values('contributing_member').distinct().count()

    def get_total_disbursed(self):
        from django.db.models import Sum
        return self.campaign_transactions.filter(
            transaction_type='PAYOUT_RECEIVED',
            status='COMPLETED'
        ).aggregate(total=Sum('amount'))['total'] or 0

    def get_balance(self):
        from decimal import Decimal
        raised = self.get_total_raised()
        disbursed = self.get_total_disbursed()
        return Decimal(str(raised)) - Decimal(str(disbursed))

    def close(self):
        """Close contributions for this campaign."""
        self.contributions_open = False
        self.save()


class CampaignContribution(models.Model):
    """Tracks individual contributions to a FundCampaign."""

    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('mobile_money', 'Mobile Money'),
        ('wallet', 'Wallet Balance'),
        ('other', 'Other'),
    ]

    campaign = models.ForeignKey(
        FundCampaign, on_delete=models.CASCADE, related_name='campaign_contributions'
    )
    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name='campaign_group_contributions', null=True, blank=True
    )
    organisation = models.ForeignKey(
        'chema.Organisation', on_delete=models.CASCADE, related_name='campaign_organisation_contributions', null=True, blank=True
    )
    contributing_member = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name='fund_campaign_contributions',
        null=True, blank=True
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(
        max_length=50, default='wallet', choices=PAYMENT_METHOD_CHOICES
    )
    transaction = models.ForeignKey(
        'wallet.Transaction', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='campaign_contribution'
    )
    contribution_date = models.DateField(auto_now_add=True)
    note = models.TextField(blank=True, help_text="Optional message with contribution")

    class Meta:
        ordering = ['-contribution_date']
        unique_together = ('campaign', 'contributing_member')

    def __str__(self):
        return (
            f"{self.contributing_member} -> {self.campaign.title}: "
            f"R{self.amount} on {self.contribution_date}"
        )