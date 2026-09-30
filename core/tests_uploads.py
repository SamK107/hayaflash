"""F-02 / F-03 : validation (taille + type reel) et noms generes cote serveur
sur les 6 champs d'upload.

Ecrit AVANT le correctif : ces tests echouent sur le code d'origine (aucun
validateur, `upload_to` en chaines fixes qui conservent le nom du client).
"""

from __future__ import annotations

import io
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from PIL import Image

from accounts.models import SellerProfile
from delivery.models import Delivery
from flash_sales.models import FlashSale
from flash_sales.services.crud import save_sale_audio
from products.models import Product, ProductMedia
from products.services.crud import add_product_image, create_product

MB = 1024 * 1024

# (modele, champ, famille) -- les 6 champs du perimetre.
IMAGE_FIELDS = [
    (SellerProfile, "avatar"),
    (FlashSale, "cover_image"),
    (ProductMedia, "file"),
]
AUDIO_FIELDS = [
    (Delivery, "audio_note"),
    (FlashSale, "description_audio"),
    (Product, "description_audio"),
]

WEBM_HEAD = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
MP3_HEAD = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
OGG_HEAD = b"OggS\x00\x02" + b"\x00" * 64
WAV_HEAD = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
M4A_HEAD = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 32
EXE_HEAD = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64


def _png_bytes(fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format=fmt)
    return buf.getvalue()


def _fake_size(upload: SimpleUploadedFile, size: int) -> SimpleUploadedFile:
    upload.size = size  # evite d'allouer 500 Mo en memoire
    return upload


def _validate(model, name, upload):
    model._meta.get_field(name).run_validators(upload)


class ImageFieldValidationTests(SimpleTestCase):
    def test_valid_png_accepted(self):
        for model, name in IMAGE_FIELDS:
            with self.subTest(field=f"{model.__name__}.{name}"):
                _validate(model, name, SimpleUploadedFile("a.png", _png_bytes()))

    def test_oversized_image_rejected(self):
        for model, name in IMAGE_FIELDS:
            with self.subTest(field=f"{model.__name__}.{name}"):
                big = _fake_size(SimpleUploadedFile("a.png", _png_bytes()), 500 * MB)
                with self.assertRaises(ValidationError):
                    _validate(model, name, big)

    def test_exactly_max_size_accepted_and_one_byte_over_rejected(self):
        model, name = IMAGE_FIELDS[0]
        ok = _fake_size(SimpleUploadedFile("a.png", _png_bytes()), 5 * MB)
        _validate(model, name, ok)
        over = _fake_size(SimpleUploadedFile("a.png", _png_bytes()), 5 * MB + 1)
        with self.assertRaises(ValidationError):
            _validate(model, name, over)

    def test_executable_disguised_as_image_rejected(self):
        for model, name in IMAGE_FIELDS:
            with self.subTest(field=f"{model.__name__}.{name}"):
                with self.assertRaises(ValidationError):
                    _validate(model, name, SimpleUploadedFile("a.png", EXE_HEAD))

    def test_html_and_svg_extensions_rejected(self):
        for model, name in IMAGE_FIELDS:
            for fname in ("a.html", "a.svg", "a.exe", "a.php"):
                with self.subTest(field=f"{model.__name__}.{name}", fname=fname):
                    with self.assertRaises(ValidationError):
                        _validate(model, name, SimpleUploadedFile(fname, _png_bytes()))

    def test_image_renamed_across_allowed_extensions_is_accepted(self):
        # Les telephones renomment souvent : le contenu reel (Pillow) prime.
        for model, name in IMAGE_FIELDS:
            with self.subTest(field=f"{model.__name__}.{name}"):
                _validate(model, name, SimpleUploadedFile("a.jpg", _png_bytes()))

    def test_gif_rejected(self):
        # .gif retire de la liste (aucun usage dans l'app)
        for model, name in IMAGE_FIELDS:
            for fname, fmt in (("a.gif", "GIF"), ("a.png", "GIF")):
                with self.subTest(field=f"{model.__name__}.{name}", fname=fname):
                    with self.assertRaises(ValidationError):
                        _validate(model, name, SimpleUploadedFile(fname, _png_bytes(fmt)))

    def test_unsupported_image_format_rejected(self):
        for model, name in IMAGE_FIELDS:
            with self.subTest(field=f"{model.__name__}.{name}"):
                with self.assertRaises(ValidationError):
                    _validate(model, name, SimpleUploadedFile("a.png", _png_bytes("BMP")))


class AudioFieldValidationTests(SimpleTestCase):
    def test_valid_audio_accepted(self):
        samples = {
            "a.webm": WEBM_HEAD,
            "a.ogg": OGG_HEAD,
            "a.mp3": MP3_HEAD,
            "a.wav": WAV_HEAD,
            "a.m4a": M4A_HEAD,
        }
        for model, name in AUDIO_FIELDS:
            for fname, head in samples.items():
                with self.subTest(field=f"{model.__name__}.{name}", fname=fname):
                    _validate(model, name, SimpleUploadedFile(fname, head))

    def test_executable_disguised_as_mp3_rejected(self):
        for model, name in AUDIO_FIELDS:
            with self.subTest(field=f"{model.__name__}.{name}"):
                with self.assertRaises(ValidationError):
                    _validate(model, name, SimpleUploadedFile("song.mp3", EXE_HEAD))

    def test_forbidden_extension_rejected(self):
        for model, name in AUDIO_FIELDS:
            for fname in ("a.exe", "a.html", "a.svg", "a.js", "a.php", "a"):
                with self.subTest(field=f"{model.__name__}.{name}", fname=fname):
                    with self.assertRaises(ValidationError):
                        _validate(model, name, SimpleUploadedFile(fname, WEBM_HEAD))

    def test_extension_content_mismatch_rejected(self):
        for model, name in AUDIO_FIELDS:
            with self.subTest(field=f"{model.__name__}.{name}"):
                with self.assertRaises(ValidationError):
                    _validate(model, name, SimpleUploadedFile("a.mp3", OGG_HEAD))

    def test_oversized_audio_rejected(self):
        for model, name in AUDIO_FIELDS:
            with self.subTest(field=f"{model.__name__}.{name}"):
                big = _fake_size(SimpleUploadedFile("a.webm", WEBM_HEAD), 500 * MB)
                with self.assertRaises(ValidationError):
                    _validate(model, name, big)

    def test_audio_limit_is_5_mo(self):
        model, name = AUDIO_FIELDS[1]
        _validate(model, name, _fake_size(SimpleUploadedFile("a.webm", WEBM_HEAD), 5 * MB))
        with self.assertRaises(ValidationError):
            _validate(
                model, name, _fake_size(SimpleUploadedFile("a.webm", WEBM_HEAD), 5 * MB + 1)
            )


class GeneratedFilenameTests(SimpleTestCase):
    """F-03 : le nom du client n'est jamais conserve, l'extension oui."""

    DANGEROUS = "../../etc/pass wd<script>é'\";.MP3"

    def _name(self, model, name, client_name):
        field = model._meta.get_field(name)
        # normalise les separateurs (os.path renvoie des '\' sous Windows)
        return field.generate_filename(None, client_name).replace("\\", "/")

    def test_client_name_not_kept_on_any_field(self):
        for model, name in IMAGE_FIELDS + AUDIO_FIELDS:
            with self.subTest(field=f"{model.__name__}.{name}"):
                out = self._name(model, name, "Mon Selfie perso (1).png")
                self.assertNotIn("Selfie", out)
                self.assertNotIn(" ", out)
                self.assertTrue(out.endswith(".png"), out)

    def test_dangerous_characters_never_reach_the_path(self):
        for model, name in IMAGE_FIELDS + AUDIO_FIELDS:
            with self.subTest(field=f"{model.__name__}.{name}"):
                out = self._name(model, name, self.DANGEROUS)
                self.assertNotIn("..", out)
                self.assertNotIn("<", out)
                self.assertNotIn("'", out)
                self.assertNotIn(";", out)
                self.assertRegex(out, r"^[A-Za-z0-9_/.\-]+$")

    def test_names_are_random_and_extension_lowercased(self):
        model, name = AUDIO_FIELDS[1]
        a = self._name(model, name, "x.WEBM")
        b = self._name(model, name, "x.WEBM")
        self.assertNotEqual(a, b)
        self.assertTrue(a.endswith(".webm"))
        self.assertRegex(a, r"^audio/sales/[0-9a-f]{32}\.webm$")

    def test_existing_directories_are_preserved(self):
        expected = {
            (SellerProfile, "avatar"): r"^sellers/avatars/",
            (FlashSale, "cover_image"): r"^flash_sales/covers/",
            (FlashSale, "description_audio"): r"^audio/sales/",
            (Product, "description_audio"): r"^audio/products/",
            (ProductMedia, "file"): r"^products/images/",
            (Delivery, "audio_note"): r"^delivery/audio/\d{4}/\d{2}/\d{2}/",
        }
        for (model, name), pattern in expected.items():
            with self.subTest(field=f"{model.__name__}.{name}"):
                self.assertRegex(self._name(model, name, "a.webm"), pattern)


class WritePathsEnforceValidationTests(TestCase):
    """Les validateurs de modele ne tournent qu'a full_clean() : les services
    qui ecrivent sans full_clean doivent les appeler explicitement."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            phone="+15550001234", password="x", display_name="S"
        )
        self.seller = SellerProfile.objects.create(user=self.user)
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            title="Drop",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            owner=self.seller,
        )

    def test_save_sale_audio_rejects_disguised_executable(self):
        with self.assertRaises(ValidationError):
            save_sale_audio(
                sale=self.sale, audio_file=SimpleUploadedFile("a.mp3", EXE_HEAD)
            )
        self.sale.refresh_from_db()
        self.assertFalse(self.sale.description_audio)

    def test_create_product_rejects_disguised_audio(self):
        with self.assertRaises(ValidationError):
            create_product(
                owner=self.seller,
                name="P",
                price=100,
                stock=1,
                description_audio=SimpleUploadedFile("a.mp3", EXE_HEAD),
            )
        self.assertFalse(Product.objects.filter(name="P").exists())

    def test_add_product_image_rejects_non_image(self):
        product = create_product(owner=self.seller, name="P2", price=100, stock=1)
        with self.assertRaises(ValidationError):
            add_product_image(
                product=product, image_file=SimpleUploadedFile("a.png", EXE_HEAD)
            )
        self.assertFalse(ProductMedia.objects.filter(product=product).exists())

    def test_saved_files_get_server_generated_names(self):
        product = create_product(owner=self.seller, name="P3", price=100, stock=1)
        media = add_product_image(
            product=product,
            image_file=SimpleUploadedFile("Mon Truc.PNG", _png_bytes()),
        )
        self.assertRegex(media.file.name, r"^products/images/[0-9a-f]{32}\.png$")
        media.file.delete(save=False)

    def test_delivery_voice_note_invalid_is_skipped_not_fatal(self):
        import base64

        from delivery.services import delivery as svc

        with mock.patch(
            "django.db.models.fields.files.FieldFile.save"
        ) as save:
            svc._attach_audio_note(
                Delivery(), base64.b64encode(EXE_HEAD).decode(), 1
            )
        save.assert_not_called()

    def test_delivery_voice_note_valid_is_attached(self):
        import base64

        from delivery.services import delivery as svc

        with mock.patch(
            "django.db.models.fields.files.FieldFile.save"
        ) as save:
            svc._attach_audio_note(
                Delivery(), base64.b64encode(WEBM_HEAD).decode(), 1
            )
        save.assert_called_once()
