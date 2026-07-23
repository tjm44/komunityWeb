from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.core.mail import send_mail
from django.conf import settings
import logging
try:
    from allauth.account.models import EmailAddress
except Exception:
    EmailAddress = None
from django.utils import timezone
from datetime import timedelta
import secrets
from .forms import CustomSignupForm, ProfileForm
from .models import CustomUser, EmailVerificationToken, Profile

# Optional import for django-allauth's EmailAddress; fall back to None if allauth isn't installed.
try:
    from allauth.account.models import EmailAddress
except Exception:
    EmailAddress = None


# Create your views here.
def profile_create(request):
    """Create or edit user's profile. User must complete profile before using home."""
    if not request.user.is_authenticated:
        return redirect('account_login')

    # Get existing profile (created by signal) or None
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        profile = None

    # If profile exists and is complete, redirect to edit view (this is not onboarding)
    if profile and profile.is_complete:
        return redirect('profile_edit')

    # If profile exists but is NOT complete (onboarding), or doesn't exist, handle it here
    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            prof = form.save(commit=False)
            prof.user = request.user
            # mark completion based on check
            prof.is_complete = prof.check_completion()
            prof.save()
            messages.success(request, 'Profile saved.')
            return redirect('group_discovery')
    else:
        form = ProfileForm(instance=profile)
    return render(request, 'user/profile_form.html', {'form': form, 'edit_mode': False})


@login_required
def profile_edit(request):
    """Edit an existing user profile."""

    # Use get_object_or_404 to ensure a profile exists.
    profile = get_object_or_404(Profile, user=request.user)

    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            prof = form.save(commit=False)
            prof.is_complete = prof.check_completion()
            prof.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('home')  # Or redirect to a profile detail page
    else:
        form = ProfileForm(instance=profile)

    return render(request, 'user/profile_form.html', {
        'form': form,
        'edit_mode': True
    })

@login_required
def profile_view(request):
    """Display the user's profile."""
    # Check if user has a profile
    # if not hasattr(request.user, 'profile'):
    #     messages.info(request, 'Please complete your profile first.')
    #     return redirect('profile_create')
    
    profile = request.user.profile
    
    # Check if profile is complete
    if not profile.is_complete:
        messages.warning(request, 'Your profile is incomplete. Please fill in all required fields.')
    
    context = {
        'profile': profile,
        'user': request.user,
    }
    
    return render(request, 'user/profile_view.html', context)

def signup(request):
    """Custom signup view with email verification.

    Creates a CustomUser with `is_active=False` and sends a verification
    email. User must click the verification link to activate their account.
    """
    if request.method == "POST":
        form = CustomSignupForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password1"]
            # Create user but leave inactive until email verified
            user = CustomUser.objects.create_user(email=email, password=password)
            user.is_active = False
            user.save()
            # Generate and send verification email
            send_verification_email(request, user)
            messages.success(request, "Account created! Please check your email to verify your account.")
            return redirect("email_verification_sent")
    else:
        form = CustomSignupForm()
    return render(request, "account/signup.html", {"form": form})


def send_verification_email(request, user):
    """Generate token and send verification email to user."""
    # Delete any existing token
    EmailVerificationToken.objects.filter(user=user).delete()
    # Create new token (24-hour expiry)
    token = secrets.token_urlsafe(48)
    expires_at = timezone.now() + timedelta(hours=24)
    EmailVerificationToken.objects.create(user=user, token=token, expires_at=expires_at)
    # Build verification link
    verification_url = request.build_absolute_uri(
        reverse("verify_email", kwargs={"token": token})
    )
    user_email = getattr(getattr(user, 'profile', None), 'email', None)
    # Log the verification URL to the console for debugging (dev only)
    logger = logging.getLogger(__name__)
    logger.info("Email verification URL for %s: %s", user_email or user, verification_url)
    print("[VERIFICATION URL]", verification_url)

    if not user_email:
        return

    # Send email (use DEFAULT_FROM_EMAIL by default)
    try:
        send_mail(
            subject="Verify Your Email",
            message=f"Click the link below to verify your email:\n\n{verification_url}\n\nThis link expires in 24 hours.",
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@chema101.com'),
            recipient_list=[user_email],
            fail_silently=False,
        )
    except Exception as e:
        # Log and notify in development; do not crash the signup flow
        logger.exception("Failed to send verification email to %s: %s", user_email, e)
        messages.error(request, "Failed to send verification email. Please contact support.")


def verify_email(request, token):
    """Verify email using token and activate user account."""
    verification = get_object_or_404(EmailVerificationToken, token=token)
    if not verification.is_valid():
        messages.error(request, "Verification link has expired. Please sign up again.")
        return redirect("signup")
    # Activate user
    user = verification.user
    user.is_active = True
    user.is_email_verified = True
    user.save()
    # Delete token
    verification.delete()
    # Ensure allauth's EmailAddress is created/marked verified so allauth
    # doesn't treat the account as unverified on subsequent logins.
    user_email = getattr(getattr(user, 'profile', None), 'email', None)
    if EmailAddress is not None and user_email:
        try:
            ea, created = EmailAddress.objects.get_or_create(user=user, email=user_email)
            ea.verified = True
            ea.primary = True
            ea.save()
        except Exception:
            # Non-fatal: keep flow working even if allauth isn't installed
            pass
    # Log user in (specify backend since multiple are configured)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    messages.success(request, "Email verified! You are now signed in.")
    
    # Redirect to welcome page for onboarding
    return redirect("welcome")


def email_verification_sent(request):
    """Show message that verification email has been sent."""
    return render(request, "account/verification_sent.html")


@login_required
def welcome(request):
    """Welcome page for new users showing the onboarding steps."""
    # If user already has a complete profile, they shouldn't see this page
    if hasattr(request.user, 'profile') and request.user.profile.is_complete:
        return redirect('home')
    return render(request, 'user/welcome.html')



