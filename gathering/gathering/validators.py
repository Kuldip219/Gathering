"""Shared validation for uploaded images (post photos and profile pictures).

Used by the forms in ``posts`` and ``accounts`` instead of model-level
validators, so that no migration is involved and users see the error inside
the form they submitted.

The image format is decided by opening the file with Pillow rather than by
trusting the file extension or the browser-supplied content type.
"""

import warnings

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

#: Largest upload we accept, in bytes (5 MB).
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: Largest image we are willing to decode, in pixels (50 megapixels).
MAX_IMAGE_PIXELS = 50_000_000

#: Formats Pillow reports for images we accept.
ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP'}

#: Formats that are real images but need converting before they can be shared.
CONVERT_FIRST_FORMATS = {'GIF', 'HEIF', 'HEIC'}

#: Fallback when Pillow cannot read the file at all but the name hints at HEIC.
CONVERT_FIRST_SUFFIXES = ('.heic', '.heif')

SIZE_MESSAGE = (
    "That photo is {size_mb:.1f} MB. Please upload an image that is 5 MB or smaller."
)
PIXEL_MESSAGE = (
    "That image is too large to process (over 50 megapixels). "
    "Please upload a smaller photo."
)
NOT_AN_IMAGE_MESSAGE = (
    "That file doesn't look like a photo. Please upload a JPEG, PNG or WebP image."
)
FORMAT_MESSAGE = "Please upload a JPEG, PNG or WebP image."
CONVERT_FIRST_MESSAGE = (
    "Please upload a JPEG, PNG or WebP image. "
    "iPhone HEIC photos need to be converted first."
)


def validate_image_upload(upload):
    """Reject uploads that are too big, not images, or the wrong format.

    Raises ``django.core.exceptions.ValidationError`` so it can be used as a
    form field validator. The file is rewound afterwards so it can still be
    saved by the model.
    """
    if not upload:
        return

    size = getattr(upload, 'size', None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ValidationError(
            SIZE_MESSAGE.format(size_mb=size / (1024 * 1024)),
            code='image_too_large',
        )

    try:
        upload.seek(0)
    except (AttributeError, OSError):
        raise ValidationError(NOT_AN_IMAGE_MESSAGE, code='invalid_image')

    image_format = None
    width = height = 0
    try:
        # Pillow only warns (or raises) on decompression bombs above its own
        # generous default thresholds, so promote the warning to an error and
        # check the pixel count against our stricter limit below.
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(upload) as image:
                image_format = image.format
                width, height = image.size
                image.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError(PIXEL_MESSAGE, code='image_too_many_pixels')
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        # Not decodable at all. A real HEIC/HEIF file lands here too unless
        # pillow-heif is installed, so use the name only to pick a friendlier
        # message - never to decide whether the file is accepted.
        name = getattr(upload, 'name', '') or ''
        if name.lower().endswith(CONVERT_FIRST_SUFFIXES):
            raise ValidationError(CONVERT_FIRST_MESSAGE, code='image_needs_converting')
        raise ValidationError(NOT_AN_IMAGE_MESSAGE, code='invalid_image')
    finally:
        try:
            upload.seek(0)
        except (AttributeError, OSError):
            pass

    if image_format not in ALLOWED_FORMATS:
        if image_format in CONVERT_FIRST_FORMATS:
            raise ValidationError(CONVERT_FIRST_MESSAGE, code='image_needs_converting')
        raise ValidationError(FORMAT_MESSAGE, code='unsupported_image_format')

    if width * height > MAX_IMAGE_PIXELS:
        raise ValidationError(PIXEL_MESSAGE, code='image_too_many_pixels')
