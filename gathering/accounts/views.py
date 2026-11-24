import logging

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .models import User
from .forms import ChangeEmailForm, ProfileEditForm, SignupForm

logger = logging.getLogger(__name__)

# Create your views here.
@login_required
def profile_redirect(request):
    return redirect('profile', username=request.user.username)


@login_required
def profile_view(request, username):
    profile_user = get_object_or_404(User, username=username)
    is_own_profile = profile_user == request.user

    form = None
    if is_own_profile:
        if request.method == 'POST':
            form = ProfileEditForm(request.POST, request.FILES, instance=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, "Profile updated.")
                return redirect('profile', username=profile_user.username)
        else:
            form = ProfileEditForm(instance=profile_user)

    context = {
        'profile_user': profile_user,
        'is_own_profile': is_own_profile,
        'form': form,
    }
    return render(request, 'accounts/profile.html', context)


def sync_allauth_email_addresses(user, old_email, new_email):
    """
    Keep allauth's EmailAddress rows in step with User.email.

    allauth resolves password-reset recipients and links Google accounts
    through these rows, so a row still holding the old address would keep the
    old login and password-reset target alive. Rows only exist once allauth
    has been involved with the account, so nothing is created here.
    """
    rows = EmailAddress.objects.filter(user=user)
    if not rows.exists():
        return

    old_rows = list(rows.filter(email__iexact=old_email))
    if not old_rows:
        return
    row = next((r for r in old_rows if r.primary), old_rows[0])

    # A row already holding the new address would collide with the rename.
    EmailAddress.objects.filter(user=user, email__iexact=new_email).exclude(pk=row.pk).delete()
    row.email = new_email
    row.save(update_fields=['email'])
    # Nothing may keep pointing at the address the user just gave up.
    EmailAddress.objects.filter(user=user, email__iexact=old_email).exclude(pk=row.pk).delete()


def _send_email_changed_notice(user, old_email, new_email, request):
    """Tell the old address about the change. Never include the password."""
    changed_at = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M')
    reset_link = request.build_absolute_uri('/')
    body = (
        f"Hello,\n\n"
        f"The login email for your Gathering account was changed on {changed_at} "
        f"from {old_email} to {new_email}.\n\n"
        f"If you made this change, nothing else is needed.\n\n"
        f"If you did not make this change, someone else may have access to your "
        f"account: reset your password from the site ({reset_link}) and contact "
        f"the family admin.\n"
    )
    try:
        send_mail(
            subject="Your Gathering login email was changed",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[old_email],
            fail_silently=False,
        )
    except Exception:
        # A mail failure must not undo or block the change itself.
        logger.exception("Could not send email-changed notice to %s", old_email)


@login_required
def change_email_view(request):
    user = request.user

    if request.method == 'POST':
        form = ChangeEmailForm(request.POST, user=user)
        if form.is_valid():
            old_email = user.email
            new_email = form.cleaned_data['new_email']

            user.email = new_email
            user.save(update_fields=['email'])
            sync_allauth_email_addresses(user, old_email, new_email)
            # Email is not part of the session auth hash, so the session and
            # the login stay valid - no re-authentication needed.

            _send_email_changed_notice(user, old_email, new_email, request)
            messages.success(request, "Login email updated.")
            return redirect('profile', username=user.username)
    else:
        form = ChangeEmailForm(user=user, initial={'new_email': user.email})

    context = {
        'form': form,
        'has_password': user.has_usable_password(),
    }
    return render(request, 'accounts/change_email.html', context)


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('profile_redirect')

    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Two backends are configured, so login() needs to be told which
            # one authenticated this user (the form saved a fresh account).
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('profile_redirect')
    else:
        form = SignupForm()

    return render(request, 'accounts/signup.html', {'form': form})
