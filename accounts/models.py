from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


phone_validator = RegexValidator(
    regex=r"^\+?[1-9]\d{7,14}$",
    message="Phone number must be in international format.",
)


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone: str, password: str | None = None, **extra_fields):
        if not phone:
            raise ValueError("The phone field is required.")

        if not extra_fields.get("display_name"):
            raise ValueError("display_name is required.")

        phone = self.normalize_phone(phone)

        user = self.model(
            phone=phone, display_name=extra_fields.pop("display_name"), **extra_fields
        )

        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        if not extra_fields.get("display_name"):
            extra_fields["display_name"] = "Admin"

        return self.create_user(phone=phone, password=password, **extra_fields)

    @staticmethod
    def normalize_phone(phone: str) -> str:
        return phone.strip().replace(" ", "")


class User(AbstractBaseUser, PermissionsMixin):
    phone = models.CharField(
        max_length=16,
        unique=True,
        validators=[phone_validator],
        help_text="E.164 phone number used for authentication.",
    )
    email = models.EmailField(blank=True)
    display_name = models.CharField(max_length=150)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)

    date_joined = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self) -> str:
        return self.display_name or self.phone


class SellerProfile(models.Model):
    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="seller_profile",
    )
    seller_code = models.CharField(max_length=20, unique=True, editable=False)
    public_slug = models.SlugField(
        max_length=80,
        unique=True,
        blank=True,
        db_index=True,
        help_text="Public URL slug for seller storefront (/s/<slug>/).",
    )
    business_name = models.CharField(
        max_length=160, blank=True, verbose_name="Nom commercial"
    )
    bio = models.TextField(blank=True, verbose_name="Biographie")
    avatar = models.ImageField(
        upload_to="sellers/avatars/",
        null=True,
        blank=True,
        verbose_name="Photo de profil",
    )
    delivery_zones = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="Zones de livraison",
        help_text="Ex: Bamako, Kati, Koulikoro",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["seller_code"]

    def __str__(self) -> str:
        return f"{self.seller_code} - {self.user}"

    def save(self, *args, **kwargs):
        if not self.seller_code:
            from accounts.services.seller_codes import generate_unique_seller_code

            self.seller_code = generate_unique_seller_code(type(self))
        if not self.public_slug:
            from accounts.services.slugs import generate_unique_seller_public_slug

            self.public_slug = generate_unique_seller_public_slug(self)

        super().save(*args, **kwargs)
