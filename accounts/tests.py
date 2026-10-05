from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import SellerProfile
from accounts.testing_helpers import NoSellerProfileMixin

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_seller_profile_generates_human_readable_code(self):
        user = User.objects.create_user(
            phone="+212600000001",
            display_name="Seller One",
            password="strong-pass-123",
        )

        profile = SellerProfile.objects.create(
            user=user,
            business_name="Shop One",
        )

        self.assertTrue(profile.seller_code.startswith("SLR-"))
        self.assertEqual(len(profile.seller_code), 12)


class NoSellerProfileAccountsTests(NoSellerProfileMixin, TestCase):
    def test_profile_and_settings(self):
        for name in ("seller_profile", "seller_settings"):
            with self.subTest(name=name):
                self.assert_no_profile_redirects(reverse(name))
