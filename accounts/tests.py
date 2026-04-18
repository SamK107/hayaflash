from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import SellerProfile

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


class AuthenticationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_and_login_flow(self):
        register_response = self.client.post(
            reverse("accounts:register"),
            {
                "phone": "+212600000002",
                "display_name": "Seller Two",
                "password": "strong-pass-123",
                "create_seller_profile": True,
                "business_name": "Shop Two",
            },
            format="json",
        )

        self.assertEqual(register_response.status_code, 201)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(SellerProfile.objects.count(), 1)

        login_response = self.client.post(
            reverse("accounts:login"),
            {
                "phone": "+212600000002",
                "password": "strong-pass-123",
            },
            format="json",
        )

        self.assertEqual(login_response.status_code, 200)

        me_response = self.client.get(reverse("accounts:me"))
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.data["phone"], "+212600000002")

        logout_response = self.client.post(reverse("accounts:logout"))
        self.assertEqual(logout_response.status_code, 204)
