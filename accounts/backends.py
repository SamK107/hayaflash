from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend

from accounts.services.users import get_user_by_phone, normalize_phone


class PhoneAuthBackend(BaseBackend):
    """
    Authenticate by phone + password (normalized like stored ``User.phone``).
    Django admin and clients may pass ``username=`` (same value as phone).
    """

    def authenticate(self, request, phone=None, password=None, **kwargs):
        UserModel = get_user_model()
        identifier = phone
        if identifier is None:
            identifier = kwargs.get(UserModel.USERNAME_FIELD)
        if identifier is None:
            identifier = kwargs.get("username")

        if identifier is None or password is None:
            return None

        if not isinstance(identifier, str):
            return None

        try:
            normalized = normalize_phone(identifier)
        except TypeError:
            return None

        if not normalized:
            return None

        user = get_user_by_phone(normalized)
        if user is None:
            return None

        if not user.check_password(password):
            return None

        if not self.user_can_authenticate(user):
            return None

        return user

    def user_can_authenticate(self, user):
        """Reject inactive users (same rule as ``ModelBackend``)."""
        return getattr(user, "is_active", True)

    def get_user(self, user_id):
        UserModel = get_user_model()
        try:
            return UserModel.objects.get(pk=user_id)
        except UserModel.DoesNotExist:
            return None
