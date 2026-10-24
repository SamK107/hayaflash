"""P2 : creation de grossiste au pilotage, entree /distrib/connexion/ (spec §5.1)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.models import AuditLog
from distrib.models import Distributor
from distrib.services.phones import build_e164, display_phone
from distrib.tests_models import make_distributor, make_seller

User = get_user_model()


class PhoneTests(TestCase):
    def test_valid_number_uses_the_chosen_code(self):
        self.assertEqual(build_e164("223", "70 00 00 01"), ("+22370000001", ""))
        self.assertEqual(build_e164("221", "77 123 45 67")[0], "+221771234567")

    def test_no_country_is_guessed(self):
        phone, err = build_e164("", "70000001")
        self.assertIsNone(phone)
        self.assertTrue(err)
        self.assertIsNone(build_e164("999", "70000001")[0])

    def test_embedded_code_is_refused(self):
        self.assertIsNone(build_e164("223", "+223 70 00 00 01")[0])
        self.assertIsNone(build_e164("223", "00223 70 00 00 01")[0])

    def test_wrong_length_and_letters_are_refused(self):
        self.assertIsNone(build_e164("223", "700000")[0])
        self.assertIsNone(build_e164("223", "7000000a")[0])
        self.assertIsNone(build_e164("223", "")[0])

    def test_display(self):
        self.assertEqual(display_phone("+22370000001"), "+223 70 00 00 01")


class ConnexionTests(TestCase):
    def setUp(self):
        self.distributor = make_distributor()

    def test_off_means_404(self):
        self.assertEqual(self.client.get("/distrib/connexion/").status_code, 404)

    @override_settings(DISTRIB_ENABLED=True)
    def test_anonymous_goes_to_login_with_next(self):
        resp = self.client.get("/distrib/connexion/")
        self.assertRedirects(resp, "/login/?next=/distrib/", fetch_redirect_response=False)

    @override_settings(DISTRIB_ENABLED=True)
    def test_next_is_kept_for_distrib_pages_only(self):
        resp = self.client.get("/distrib/connexion/?next=/distrib/invitation/3/")
        self.assertRedirects(resp, "/login/?next=/distrib/invitation/3/", fetch_redirect_response=False)
        for evil in ("https://evil.example/", "//evil.example/", "/seller/", "/distrib/\\x"):
            resp = self.client.get("/distrib/connexion/", {"next": evil})
            self.assertRedirects(resp, "/login/?next=/distrib/", fetch_redirect_response=False)

    @override_settings(DISTRIB_ENABLED=True)
    def test_logged_in_distributor_without_shop_goes_to_distrib(self):
        # Le piege : /login/ ignore `next` pour un utilisateur deja connecte.
        self.client.force_login(self.distributor.user)
        resp = self.client.get("/distrib/connexion/")
        self.assertRedirects(resp, "/distrib/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/distrib/").status_code, 200)

    @override_settings(DISTRIB_ENABLED=True)
    def test_logged_in_non_distributor_gets_an_explanation_not_a_500(self):
        self.client.force_login(make_seller().user)
        resp = self.client.get("/distrib/connexion/")
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "n'est pas un compte grossiste", status_code=403)

    @override_settings(DISTRIB_ENABLED=True)
    def test_logged_in_non_distributor_follows_a_distrib_next(self):
        self.client.force_login(make_seller().user)
        resp = self.client.get("/distrib/connexion/?next=/distrib/invitation/3/")
        self.assertRedirects(resp, "/distrib/invitation/3/", fetch_redirect_response=False)

    @override_settings(DISTRIB_ENABLED=True)
    def test_full_login_flow_for_a_user_without_seller_profile(self):
        self.distributor.user.set_password("secret-123-xyz")
        self.distributor.user.save()
        resp = self.client.post(
            "/login/?next=/distrib/", {"phone": "+22371000001", "password": "secret-123-xyz"}
        )
        self.assertRedirects(resp, "/distrib/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/distrib/").status_code, 200)


@override_settings(DISTRIB_ENABLED=True)
class PilotageTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            phone="+22390000009", password="x", display_name="Equipe", is_staff=True
        )

    def payload(self, **over):
        data = {
            "business_name": "Gros Bamako",
            "display_name": "Moussa Traoré",
            "calling_code": "223",
            "phone": "71 00 00 01",
            "orange_money_number": "",
            "commission_rate": "6",
            "pilot_until": "2026-12-31",
        }
        data.update(over)
        return data

    def test_staff_only(self):
        seller_user = make_seller().user
        distributor_user = make_distributor().user
        for url in ("/distrib/pilotage/", "/distrib/pilotage/grossistes/nouveau/"):
            self.assertEqual(self.client.get(url).status_code, 302)  # anonyme
            self.client.force_login(seller_user)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.client.force_login(distributor_user)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.client.logout()

    def test_pilotage_off_is_404_even_for_staff(self):
        self.client.force_login(self.staff)
        with override_settings(DISTRIB_ENABLED=False):
            self.assertEqual(self.client.get("/distrib/pilotage/").status_code, 404)

    def test_create_with_new_account_shows_a_temporary_password_once(self):
        self.client.force_login(self.staff)
        resp = self.client.post("/distrib/pilotage/grossistes/nouveau/", self.payload())
        self.assertEqual(resp.status_code, 200)
        d = Distributor.objects.get(business_name="Gros Bamako")
        self.assertEqual(d.user.phone, "+22371000001")
        self.assertEqual(d.created_by, self.staff)
        self.assertEqual(str(d.pilot_until), "2026-12-31")
        password = resp.context["temporary_password"]
        self.assertTrue(password)
        self.assertContains(resp, password)
        self.assertEqual(resp["Cache-Control"], "no-store")
        self.assertTrue(d.user.check_password(password))
        # Le mot de passe n'est plus jamais montre.
        again = self.client.get("/distrib/pilotage/")
        self.assertNotContains(again, password)
        self.assertTrue(
            AuditLog.objects.filter(action="distrib.distributor_created", entity_id=d.pk).exists()
        )

    def test_new_grossiste_can_log_in_with_the_temporary_password(self):
        self.client.force_login(self.staff)
        resp = self.client.post("/distrib/pilotage/grossistes/nouveau/", self.payload())
        password = resp.context["temporary_password"]
        self.client.logout()
        login = self.client.post("/login/?next=/distrib/", {"phone": "+22371000001", "password": password})
        self.assertRedirects(login, "/distrib/", fetch_redirect_response=False)

    def test_existing_account_is_attached_without_touching_its_password(self):
        seller = make_seller("+22371000001", "Fatou")
        seller.user.set_password("deja-la-123")
        seller.user.save()
        self.client.force_login(self.staff)
        resp = self.client.post("/distrib/pilotage/grossistes/nouveau/", self.payload())
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["temporary_password"])
        d = Distributor.objects.get(user=seller.user)
        seller.user.refresh_from_db()
        self.assertTrue(seller.user.check_password("deja-la-123"))
        self.assertEqual(d.user_id, seller.user_id)

    def test_same_phone_twice_is_refused(self):
        make_distributor("+22371000001")
        self.client.force_login(self.staff)
        resp = self.client.post("/distrib/pilotage/grossistes/nouveau/", self.payload())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "correspond déjà à un grossiste")
        self.assertEqual(Distributor.objects.count(), 1)

    def test_invalid_phone_or_missing_name_creates_nothing(self):
        self.client.force_login(self.staff)
        for over in ({"phone": "123"}, {"business_name": ""}, {"calling_code": "999"}, {"commission_rate": "150"}):
            resp = self.client.post("/distrib/pilotage/grossistes/nouveau/", self.payload(**over))
            self.assertEqual(resp.status_code, 200, over)
        self.assertEqual(Distributor.objects.count(), 0)
        self.assertEqual(User.objects.filter(phone="+22371000001").count(), 0)

    def test_orange_money_number_is_stored_in_e164(self):
        self.client.force_login(self.staff)
        self.client.post(
            "/distrib/pilotage/grossistes/nouveau/", self.payload(orange_money_number="72 00 00 02")
        )
        self.assertEqual(Distributor.objects.get().orange_money_number, "+22372000002")

    def test_list_shows_distributors(self):
        make_distributor(name="Gros A")
        self.client.force_login(self.staff)
        self.assertContains(self.client.get("/distrib/pilotage/"), "Gros A")
