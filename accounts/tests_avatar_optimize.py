"""Avatar vendeur redimensionne a l'upload (core/services/image_optimize.py)."""

from __future__ import annotations

import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from accounts.models import SellerProfile
from core.services.image_optimize import DEFAULT_MAX_DIMENSION

User = get_user_model()

_MEDIA_ROOT = tempfile.mkdtemp(prefix="hf-avatar-media-")


def _jpeg(name: str, size: tuple[int, int]) -> SimpleUploadedFile:
    buffer = BytesIO()
    Image.new("RGB", size, (255, 77, 46)).save(buffer, format="JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class SellerAvatarOptimizeTests(TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self) -> None:
        self.user = User.objects.create_user(phone="+15550004444", password="x", display_name="Awa Shop"
        )

    def _stored_size(self, profile: SellerProfile) -> tuple[int, int]:
        profile.refresh_from_db()
        with profile.avatar.open("rb") as fh:
            return Image.open(fh).size

    def test_large_avatar_is_resized_on_upload(self) -> None:
        profile = SellerProfile.objects.create(
            user=self.user, avatar=_jpeg("grand.jpg", (3000, 3000))
        )
        self.assertLessEqual(max(self._stored_size(profile)), DEFAULT_MAX_DIMENSION)

    def test_small_avatar_is_left_untouched(self) -> None:
        profile = SellerProfile.objects.create(
            user=self.user, avatar=_jpeg("petit.jpg", (400, 300))
        )
        self.assertEqual(self._stored_size(profile), (400, 300))

    def test_profile_without_avatar_saves(self) -> None:
        profile = SellerProfile.objects.create(user=self.user)
        self.assertFalse(profile.avatar)
