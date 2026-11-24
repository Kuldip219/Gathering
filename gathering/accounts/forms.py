from allauth.account.models import EmailAddress
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from gathering.validators import validate_image_upload

from .models import User

TEXT_INPUT_CLASSES = (
    "w-full rounded-md border border-gray-300 px-3 py-2 text-sm "
    "focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500"
)


class LoginForm(AuthenticationForm):
    """
    The field is still named 'username' because Django's AuthenticationForm
    hardcodes that name internally — but since USERNAME_FIELD is now
    'email' on the User model, authenticate() treats whatever is typed
    here as an email address. We just relabel it for the user.
    """
    username = forms.CharField(
        label="Email",
        widget=forms.EmailInput(attrs={'class': TEXT_INPUT_CLASSES, 'autofocus': True})
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={'class': TEXT_INPUT_CLASSES})
    )

    def clean_username(self):
        # Emails are stored lowercased, so be forgiving about casing on login.
        return self.cleaned_data.get('username', '').lower()


class SignupForm(UserCreationForm):
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={'class': TEXT_INPUT_CLASSES, 'autofocus': True})
    )
    username = forms.CharField(
        label="Username",
        widget=forms.TextInput(attrs={'class': TEXT_INPUT_CLASSES}),
        help_text="This is the name other family members will see on your posts."
    )

    class Meta:
        model = User
        fields = ['email', 'username', 'password1', 'password2']

    def clean_email(self):
        # Normalize to lowercase so unique=True can't be bypassed by casing.
        email = self.cleaned_data.get('email')
        return email.lower() if email else email

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].label = "Password"
        self.fields['password2'].label = "Confirm password"
        self.fields['password1'].widget.attrs.update({'class': TEXT_INPUT_CLASSES})
        self.fields['password2'].widget.attrs.update({'class': TEXT_INPUT_CLASSES})


class ChangeEmailForm(forms.Form):
    """Change the login email, confirmed with the current password."""

    new_email = forms.EmailField(
        label="New email",
        widget=forms.EmailInput(attrs={'class': TEXT_INPUT_CLASSES, 'autofocus': True}),
    )
    current_password = forms.CharField(
        label="Current password",
        widget=forms.PasswordInput(attrs={'class': TEXT_INPUT_CLASSES}),
        required=False,
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        # Accounts that sign in with Google have no usable password, so there
        # is nothing to confirm. This branch must stay unreachable for anyone
        # who does have a password, hence the field is only dropped here.
        if user is None or not user.has_usable_password():
            self.fields.pop('current_password')
        else:
            self.fields['current_password'].required = True

    def clean_new_email(self):
        # Same normalisation as SignupForm.clean_email.
        email = (self.cleaned_data.get('new_email') or '').strip().lower()
        if self.user is not None and email == (self.user.email or '').lower():
            raise forms.ValidationError("That is already your login email.")
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            # Same wording Django's UserCreationForm uses at signup.
            raise forms.ValidationError("A user with that email already exists.")
        # An allauth EmailAddress row owned by somebody else would make
        # password reset and Google linking ambiguous.
        if EmailAddress.objects.filter(email__iexact=email).exclude(user=self.user).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return email

    def clean_current_password(self):
        password = self.cleaned_data.get('current_password')
        if password is None or self.user is None:
            return password
        if not self.user.check_password(password):
            raise forms.ValidationError("That password is not correct.")
        return password


class ProfileEditForm(forms.ModelForm):
    # A plain FileField rather than ImageField so the shared validator owns
    # the image checks and its message is what the user sees.
    profile_picture = forms.FileField(
        required=False,
        validators=[validate_image_upload],
        # FileField does not add this itself; ImageField used to.
        widget=forms.ClearableFileInput(
            attrs={'accept': 'image/jpeg,image/png,image/webp'}
        ),
    )

    class Meta:
        model = User
        fields = ['bio', 'profile_picture']
        widgets = {
            'bio': forms.Textarea(attrs={
                'class': TEXT_INPUT_CLASSES,
                'rows': 4,
                'placeholder': 'Write something about yourself...',
            }),
        }
