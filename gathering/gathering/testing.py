"""Small helpers shared by the test suites of the project's apps."""

import io
import os
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

CONTENT_TYPES = {
    'JPEG': 'image/jpeg',
    'PNG': 'image/png',
    'WEBP': 'image/webp',
    'GIF': 'image/gif',
}


def make_test_image(name='test.png', size=(4, 4), color=(10, 20, 30), image_format='PNG'):
    """Return a tiny, valid in-memory image as an uploadable file."""
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, format=image_format)
    return SimpleUploadedFile(
        name,
        buffer.getvalue(),
        content_type=CONTENT_TYPES.get(image_format, 'application/octet-stream'),
    )


def make_oversized_test_image(name='huge.png', size=(1500, 1500)):
    """Return a valid PNG whose bytes are larger than the 5 MB upload limit.

    Random noise barely compresses, so the encoded file is bigger than the
    raw pixel data would suggest.
    """
    width, height = size
    buffer = io.BytesIO()
    noise = os.urandom(width * height * 3)
    Image.frombytes('RGB', (width, height), noise).save(
        buffer, format='PNG', compress_level=1
    )
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


def make_text_upload(name='photo.jpg', content=b'this is not an image'):
    """Return a plain-text file that pretends to be a photo by its name."""
    return SimpleUploadedFile(name, content, content_type='image/jpeg')


class TemporaryMediaRootMixin:
    """Point MEDIA_ROOT at a throwaway directory for the duration of a TestCase.

    Uploads made by the tests land there instead of in the real
    ``gathering/media/`` folder, and the directory is removed afterwards.
    """

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='gathering-test-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            cls._media_override.disable()
            shutil.rmtree(cls._media_root, ignore_errors=True)
