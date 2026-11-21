"""Small helpers shared by the test suites of the project's apps."""

import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image


def make_test_image(name='test.png', size=(4, 4), color=(10, 20, 30)):
    """Return a tiny, valid in-memory PNG as an uploadable file."""
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


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
