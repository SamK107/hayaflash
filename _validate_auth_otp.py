import re
from unittest.mock import patch

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.test import RequestFactory

from accounts.services.otp import send_otp, verify_phone_otp
from django.contrib.auth import get_user_model

rf = RequestFactory()
req = rf.post("/")
User = get_user_model()
phone = "+22599123458"
u, _ = User.objects.get_or_create(
    phone=phone,
    defaults={"display_name": "Auth OTP Test"},
)
u.set_password("secret123!")
u.is_active = True
u.is_phone_verified = False
u.save()

assert authenticate(req, phone=phone, password="secret123!") == u
assert authenticate(req, username=phone, password="secret123!") == u
assert authenticate(req, phone=phone, password="wrong") is None

captured: dict[str, str] = {}


def fake_send(p: str, msg: str) -> None:
    captured["msg"] = msg


with patch("accounts.services.sms.send_sms", fake_send):
    send_otp(phone)
code = re.search(r"(\d{6})", captured["msg"]).group(1)
assert verify_phone_otp(phone, code) is True

cache.clear()
u.is_phone_verified = False
u.save(update_fields=["is_phone_verified"])
with patch("accounts.services.sms.send_sms", fake_send):
    send_otp(phone)
code2 = re.search(r"(\d{6})", captured["msg"]).group(1)
for _ in range(5):
    assert verify_phone_otp(phone, "000000") is False
assert verify_phone_otp(phone, code2) is False

print("validate auth+otp+bruteforce OK")
