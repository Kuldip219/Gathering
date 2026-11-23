from django import forms

from gathering.validators import validate_image_upload

from .models import Post

INPUT_CLASSES = (
    "w-full rounded-md border border-gray-300 px-3 py-2 text-sm "
    "focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500"
)


class PostForm(forms.ModelForm):
    # A plain FileField rather than ImageField so the shared validator owns
    # the image checks and its message is what the user sees.
    image = forms.FileField(
        required=False,
        validators=[validate_image_upload],
        # FileField does not add this itself; ImageField used to.
        widget=forms.ClearableFileInput(
            attrs={'accept': 'image/jpeg,image/png,image/webp'}
        ),
    )

    class Meta:
        model = Post
        fields = ['image', 'caption']
        widgets = {
            'caption': forms.Textarea(attrs={
                'class': INPUT_CLASSES,
                'rows': 3,
                'placeholder': "Write a caption...",
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('image') and not cleaned_data.get('caption'):
            raise forms.ValidationError("Add a photo or write something before posting.")
        return cleaned_data
