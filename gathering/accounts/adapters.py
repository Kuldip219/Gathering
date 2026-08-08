from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from .models import User


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        # If this Google account is already linked to a user, nothing to do.
        if sociallogin.is_existing:
            return

        email = sociallogin.account.extra_data.get('email')
        if not email:
            return

        try:
            existing_user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return

        # An account with this email already exists (created via our normal
        # signup form) — link this Google identity to it instead of trying
        # to create a duplicate, then log them straight in.
        sociallogin.connect(request, existing_user)
