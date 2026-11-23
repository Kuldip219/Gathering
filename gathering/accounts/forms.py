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


class ProfileEditForm(forms.ModelForm):
    # A plain FileField rather than ImageField so the shared validator owns
    # the image checks and its message is what the user sees.
    profile_picture = forms.FileField(
        required=False, validators=[validate_image_upload]
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
