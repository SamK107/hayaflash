"""P3 : invitations, bandeau du tableau de bord vendeur, page de consentement (spec §5.2)."""

from __future__ import annotations

from django.test import TestCase, override_settings

from distrib.models import ResellerInvite
from distrib.services import invites as svc
from distrib.tests_models import make_distributor, make_seller

S = ResellerInvite.Status


def invite(distributor, phone="+22370000001", name="Awa", **extra):
    return ResellerInvite.objects.create(distributor=distributor, display_name=name, phone=phone, **extra)


@override_settings(DISTRIB_ENABLED=True)
class InviteServiceTests(TestCase):
    def setUp(self):
        self.d = make_distributor()

    def test_invite_creates_invited_row(self):
        inv = svc.invite_reseller(distributor=self.d, display_name=" Awa ", phone="+22370000001")
        self.assertEqual((inv.status, inv.display_name, inv.seller), (S.INVITED, "Awa", None))

    def test_duplicates_are_refused_with_a_clear_message(self):
        inv = invite(self.d)
        from django.core.exceptions import ValidationError

        with self.assertRaisesMessage(ValidationError, "déjà invité"):
            svc.invite_reseller(distributor=self.d, display_name="Awa", phone=inv.phone)
        inv.status = S.ACCEPTED
        inv.save()
        with self.assertRaisesMessage(ValidationError, "déjà rattaché"):
            svc.invite_reseller(distributor=self.d, display_name="Awa", phone=inv.phone)

    def test_cannot_invite_oneself(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            svc.invite_reseller(distributor=self.d, display_name="Moi", phone=self.d.user.phone)

    def test_declined_or_revoked_can_be_invited_again_and_must_consent_again(self):
        seller = make_seller()
        for status in (S.DECLINED, S.REVOKED):
            inv = invite(self.d, seller=seller, status=status)
            again = svc.invite_reseller(distributor=self.d, display_name="Awa", phone=inv.phone)
            self.assertEqual(again.pk, inv.pk)
            self.assertEqual((again.status, again.seller), (S.INVITED, None))
            inv.delete()

    def test_revoke_then_second_revoke_is_refused(self):
        inv = invite(self.d, status=S.ACCEPTED)
        svc.revoke_invite(invite=inv)
        inv.refresh_from_db()
        self.assertEqual(inv.status, S.REVOKED)
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            svc.revoke_invite(invite=inv)

    def test_answer_requires_the_invited_number_and_a_shop(self):
        from django.core.exceptions import PermissionDenied

        inv = invite(self.d, phone="+22370000001")
        stranger = make_seller("+22370000002", "Autre")
        with self.assertRaises(PermissionDenied):
            svc.answer_invite(invite=inv, user=stranger.user, accept=True)
        inv.refresh_from_db()
        self.assertEqual((inv.status, inv.seller), (S.INVITED, None))

    def test_answer_only_once(self):
        from django.core.exceptions import ValidationError

        seller = make_seller()
        inv = invite(self.d)
        svc.answer_invite(invite=inv, user=seller.user, accept=True)
        with self.assertRaises(ValidationError):
            svc.answer_invite(invite=inv, user=seller.user, accept=False)
        inv.refresh_from_db()
        self.assertEqual((inv.status, inv.seller), (S.ACCEPTED, seller))
        self.assertIsNotNone(inv.answered_at)


@override_settings(DISTRIB_ENABLED=True)
class ResellerListViewTests(TestCase):
    def setUp(self):
        self.d = make_distributor()
        self.client.force_login(self.d.user)

    def test_add_invitation_normalizes_with_the_chosen_code(self):
        resp = self.client.post(
            "/distrib/revendeurs/", {"display_name": "Awa", "calling_code": "223", "phone": "70 00 00 01"}
        )
        self.assertRedirects(resp, "/distrib/revendeurs/")
        inv = ResellerInvite.objects.get()
        self.assertEqual((inv.phone, inv.status, inv.distributor), ("+22370000001", S.INVITED, self.d))

    def test_bad_number_creates_nothing(self):
        resp = self.client.post(
            "/distrib/revendeurs/", {"display_name": "Awa", "calling_code": "223", "phone": "123"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ResellerInvite.objects.count(), 0)

    def test_duplicate_shows_an_error(self):
        invite(self.d)
        resp = self.client.post(
            "/distrib/revendeurs/", {"display_name": "Awa", "calling_code": "223", "phone": "70 00 00 01"}
        )
        self.assertContains(resp, "déjà invité")
        self.assertEqual(ResellerInvite.objects.count(), 1)

    def test_revoke(self):
        inv = invite(self.d, status=S.ACCEPTED)
        resp = self.client.post(f"/distrib/revendeurs/{inv.pk}/revoquer/")
        self.assertRedirects(resp, "/distrib/revendeurs/")
        inv.refresh_from_db()
        self.assertEqual(inv.status, S.REVOKED)

    def test_revoke_needs_post(self):
        inv = invite(self.d, status=S.ACCEPTED)
        self.assertEqual(self.client.get(f"/distrib/revendeurs/{inv.pk}/revoquer/").status_code, 405)

    def test_cloisonnement_between_distributors(self):
        other = make_distributor("+22371000002", "Autre gros")
        foreign = invite(other, phone="+22370000009", name="Voisine", status=S.ACCEPTED)
        page = self.client.get("/distrib/revendeurs/")
        self.assertNotContains(page, "Voisine")
        self.assertEqual(self.client.post(f"/distrib/revendeurs/{foreign.pk}/revoquer/").status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, S.ACCEPTED)

    def test_reseller_and_anonymous_cannot_use_the_list(self):
        self.client.logout()
        self.assertEqual(self.client.get("/distrib/revendeurs/").status_code, 302)
        self.client.force_login(make_seller().user)
        self.assertEqual(self.client.get("/distrib/revendeurs/").status_code, 403)


@override_settings(DISTRIB_ENABLED=True)
class BannerTests(TestCase):
    def setUp(self):
        self.d = make_distributor()
        self.seller = make_seller("+22370000001")

    def home(self, user=None):
        self.client.force_login(user or self.seller.user)
        return self.client.get("/seller/")

    def test_banner_shows_for_the_invited_number_only(self):
        inv = invite(self.d, phone="+22370000001")
        resp = self.home()
        self.assertContains(resp, "Gros Bamako vous invite")
        self.assertContains(resp, f"/distrib/invitation/{inv.pk}/")
        other = make_seller("+22370000002", "Fanta")
        self.assertNotContains(self.home(other.user), "vous invite")

    def test_number_match_is_exact_e164(self):
        invite(self.d, phone="+22170000001")  # meme numero national, autre pays
        self.assertNotContains(self.home(), "vous invite")

    def test_no_banner_once_answered_or_revoked(self):
        for status in (S.ACCEPTED, S.DECLINED, S.REVOKED):
            inv = invite(self.d, status=status)
            self.assertNotContains(self.home(), "vous invite", msg_prefix=status)
            inv.delete()

    def test_no_banner_for_an_inactive_distributor(self):
        invite(self.d)
        self.d.is_active = False
        self.d.save()
        self.assertNotContains(self.home(), "vous invite")

    def test_switch_off_means_no_banner(self):
        invite(self.d)
        with override_settings(DISTRIB_ENABLED=False):
            self.assertNotContains(self.home(), "vous invite")

    def test_accepted_reseller_sees_a_link_to_my_wholesalers(self):
        invite(self.d, status=S.ACCEPTED, seller=self.seller)
        self.assertContains(self.home(), "/distrib/mes-grossistes/")

    def test_a_failure_in_the_banner_never_breaks_the_dashboard(self):
        from unittest import mock

        invite(self.d)
        with mock.patch(
            "distrib.templatetags.distrib_tags.pending_invites_for", side_effect=RuntimeError("boom")
        ):
            resp = self.home()
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "vous invite")

    def test_dashboard_is_unchanged_without_invitation(self):
        resp = self.home()
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "dx-banner")


@override_settings(DISTRIB_ENABLED=True)
class ConsentPageTests(TestCase):
    def setUp(self):
        self.d = make_distributor()
        self.seller = make_seller("+22370000001")
        self.inv = invite(self.d, phone="+22370000001")
        self.url = f"/distrib/invitation/{self.inv.pk}/"

    def test_page_states_what_is_shared(self):
        self.client.force_login(self.seller.user)
        resp = self.client.get(self.url)
        self.assertContains(resp, "verra les commandes des produits que vous importez")
        self.assertContains(resp, "adresse de livraison")
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, S.INVITED)  # lire n'engage a rien

    def test_accept_attaches_the_shop(self):
        self.client.force_login(self.seller.user)
        resp = self.client.post(self.url, {"decision": "accept"})
        self.assertRedirects(resp, "/distrib/mes-grossistes/", fetch_redirect_response=False)
        self.inv.refresh_from_db()
        self.assertEqual((self.inv.status, self.inv.seller), (S.ACCEPTED, self.seller))
        self.assertContains(self.client.get("/distrib/mes-grossistes/"), "Gros Bamako")

    def test_decline_attaches_nothing(self):
        self.client.force_login(self.seller.user)
        self.client.post(self.url, {"decision": "decline"})
        self.inv.refresh_from_db()
        self.assertEqual((self.inv.status, self.inv.seller), (S.DECLINED, None))

    def test_no_attachment_without_an_explicit_answer(self):
        self.client.force_login(self.seller.user)
        for payload in ({}, {"decision": "maybe"}):
            self.client.post(self.url, payload)
        self.inv.refresh_from_db()
        self.assertEqual((self.inv.status, self.inv.seller), (S.INVITED, None))

    def test_another_shop_cannot_see_or_answer(self):
        stranger = make_seller("+22370000002", "Fanta")
        self.client.force_login(stranger.user)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {"decision": "accept"}).status_code, 404)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, S.INVITED)

    def test_anonymous_is_sent_to_login_and_back(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/distrib/connexion/", resp["Location"])

    def test_answering_twice_does_nothing_more(self):
        self.client.force_login(self.seller.user)
        self.client.post(self.url, {"decision": "accept"})
        self.client.post(self.url, {"decision": "decline"})
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, S.ACCEPTED)

    def test_user_without_shop_is_forbidden(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(phone="+22370000044", password="x", display_name="Sans")
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_off_means_404(self):
        self.client.force_login(self.seller.user)
        with override_settings(DISTRIB_ENABLED=False):
            self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_revoked_invitation_cannot_be_accepted_through_a_stale_page(self):
        self.client.force_login(self.seller.user)
        self.inv.status = S.REVOKED
        self.inv.save()
        self.client.post(self.url, {"decision": "accept"})
        self.inv.refresh_from_db()
        self.assertEqual((self.inv.status, self.inv.seller), (S.REVOKED, None))
