"""Accès Pro offert 30 jours pendant l'essai (sans paiement Orange).

Mécanisme réutilisé, sans nouveau modèle : ``Subscription.plan = pro`` avec ``expires_at``.
Un abonnement expiré retombe de lui-même sur le plan gratuit (``is_pro`` faux). Aucune ligne
``SubscriptionPayment`` n'est créée : ni le chiffre d'affaires, ni les commissions ne le voient.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import SellerProfile
from core.models import AuditLog, audit
from partners.models import Partner, PartnerPhase
from subscriptions.models import Plan, Subscription

ACTION = "partner.pro_trial_granted"
REASON = "essai partenaire"


def grant_pro_trial(partner: Partner, actor=None) -> Subscription:
    """Offre 30 jours de plan Pro au vendeur du partenaire. Une seule fois par vendeur."""
    if partner.phase != PartnerPhase.TRIAL:
        raise ValidationError("L'accès Pro offert n'est possible que pendant l'essai du partenaire.")
    seller = SellerProfile.objects.filter(user__phone=partner.phone).first()
    if seller is None:
        raise ValidationError("Aucun compte vendeur n'existe avec le numéro de ce partenaire.")
    with transaction.atomic():
        SellerProfile.objects.select_for_update().get(pk=seller.pk)
        if AuditLog.objects.filter(action=ACTION, entity_type="SellerProfile", entity_id=seller.pk).exists():
            raise ValidationError("L'accès Pro offert a déjà été accordé à ce vendeur : une seule fois.")
        sub, _ = Subscription.objects.select_for_update().get_or_create(seller=seller)
        if sub.is_paid:
            raise ValidationError("Ce vendeur a déjà un abonnement payant actif : rien n'est offert.")
        sub.plan = Plan.PRO
        sub.expires_at = timezone.now() + timedelta(days=settings.PARTNER_TRIAL_DAYS)
        sub.save()
        audit(
            ACTION,
            entity_type="SellerProfile",
            entity_id=seller.pk,
            actor=actor,
            reason=REASON,
            partner_id=partner.pk,
            expires_at=sub.expires_at.isoformat(),
        )
    return sub
