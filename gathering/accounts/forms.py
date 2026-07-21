from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import User

TEXT_INPUT_CLASSES = (
    "w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
    "focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500"
)


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={"class": TEXT_INPUT_CLASSES, 'autofocus': True})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": TEXT_INPUT_CLASSES})
    )


class ProfileForm(forms.ModelForm):
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