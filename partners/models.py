"""Programme partenaires : partenaires, clics, parrainages, commissions, versements.

Montants en FCFA entiers (RM-12), jamais de centimes. Les règles de calcul vivent
dans ``partners/services/`` ; ici, uniquement les données et leurs contraintes.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from partners.services.dates import add_months

CODE_RE = re.compile(r"^[A-Z0-9]{4,12}$")


def default_commission_percent() -> int:
    return settings.PARTNER_COMMISSION_PERCENT


def today() -> date:
    return timezone.localdate()


class PartnerKind(models.TextChoices):
    SELLER_PILOT = "seller_pilot", "Vendeur pilote"
    CREATOR = "creator", "Créateur de contenu"


class PartnerStatus(models.TextChoices):
    PROSPECT = "prospect", "Prospect"
    ACTIVE = "active", "Actif"
    PAUSED = "paused", "En pause"
    ENDED = "ended", "Terminé"
    SLOT_RELEASED = "slot_released", "Place libérée"


class PartnerPhase(models.TextChoices):
    NONE = "none", "Aucune"
    TRIAL = "trial", "Essai"
    CONTRACT = "contract", "Contrat"
    ENDED = "ended", "Terminée"


# Statuts qui occupent une place de fondateur (et seulement en phase contrat).
SLOT_HOLDING_STATUSES = (PartnerStatus.ACTIVE, PartnerStatus.PAUSED)


class Partner(models.Model):
    name = models.CharField(max_length=120, verbose_name="Nom")
    phone = models.CharField(max_length=32, unique=True, verbose_name="Téléphone")
    code = models.CharField(
        max_length=12,
        unique=True,
        verbose_name="Code du partenaire",
        help_text="4 à 12 caractères : lettres majuscules et chiffres.",
    )
    kind = models.CharField(
        max_length=16,
        choices=PartnerKind.choices,
        default=PartnerKind.CREATOR,
        verbose_name="Type",
    )
    status = models.CharField(
        max_length=16,
        choices=PartnerStatus.choices,
        default=PartnerStatus.ACTIVE,
        db_index=True,
        verbose_name="Statut",
    )
    phase = models.CharField(
        max_length=8,
        choices=PartnerPhase.choices,
        default=PartnerPhase.CONTRACT,
        db_index=True,
        verbose_name="Phase",
        help_text="Aucune, essai de 30 jours, contrat d'un an, ou terminée.",
    )
    trial_start = models.DateField(null=True, blank=True, verbose_name="Début de l'essai")
    trial_end = models.DateField(
        null=True, blank=True, verbose_name="Fin de l'essai", help_text="Calculée : début + 30 jours."
    )
    cite_shop_consent = models.BooleanField(
        default=False, verbose_name="Autorise à citer sa boutique"
    )
    shop_name = models.CharField(max_length=160, blank=True, verbose_name="Boutique")
    is_founder = models.BooleanField(default=False, verbose_name="Fondateur")
    contract_start = models.DateField(default=today, verbose_name="Début du contrat")
    contract_end = models.DateField(
        blank=True, verbose_name="Fin du contrat", help_text="Calculée : début + 12 mois."
    )
    commission_percent = models.PositiveSmallIntegerField(
        default=default_commission_percent,
        verbose_name="Commission (%)",
        help_text="Figée à la création du partenaire.",
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Partenaire"
        verbose_name_plural = "Partenaires"
        constraints = [
            models.CheckConstraint(
                condition=Q(commission_percent__lte=100),
                name="partner_commission_percent_lte_100",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    # -- validation -----------------------------------------------------------
    def _normalise(self) -> None:
        from accounts.services.users import normalize_phone

        self.code = (self.code or "").strip().upper()
        self.phone = normalize_phone(self.phone or "")
        if not self.contract_end:
            self.contract_end = add_months(
                self.contract_start, settings.PARTNER_CONTRACT_MONTHS
            )
        if self.trial_start and not self.trial_end:
            self.trial_end = self.trial_start + timedelta(days=settings.PARTNER_TRIAL_DAYS)

    def check_founder_slot(self) -> None:
        """Au plus PARTNER_FOUNDER_SLOTS fondateurs actifs ou en pause."""
        if (
            not self.is_founder
            or self.status not in SLOT_HOLDING_STATUSES
            or self.phase != PartnerPhase.CONTRACT
        ):
            return
        taken = (
            Partner.objects.filter(
                is_founder=True, status__in=SLOT_HOLDING_STATUSES, phase=PartnerPhase.CONTRACT
            )
            .exclude(pk=self.pk)
            .count()
        )
        if taken >= settings.PARTNER_FOUNDER_SLOTS:
            raise ValidationError(
                f"Les {settings.PARTNER_FOUNDER_SLOTS} places de fondateur sont toutes "
                "occupées (actives ou en pause). Libérez une place avant d'en créer une autre."
            )

    def clean(self) -> None:
        super().clean()
        self._normalise()
        if not CODE_RE.match(self.code):
            raise ValidationError(
                {"code": "Le code doit contenir 4 à 12 lettres majuscules ou chiffres, sans espace."}
            )
        if self.commission_percent is not None and self.commission_percent > 100:
            raise ValidationError({"commission_percent": "Le pourcentage ne peut pas dépasser 100."})
        self.check_founder_slot()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    # -- règles de contrat ----------------------------------------------------
    @property
    def accepts_new_referrals(self) -> bool:
        """Nouvelles inscriptions via le lien : partenaire actif, en essai ou sous contrat en cours.

        Un prospect, une phase « aucune » ou « terminée » n'en reçoit pas. Les droits déjà
        acquis ne dépendent pas de cette règle.
        """
        if self.status != PartnerStatus.ACTIVE:
            return False
        if self.phase == PartnerPhase.CONTRACT:
            return today() <= self.contract_end
        if self.phase == PartnerPhase.TRIAL:
            return bool(self.trial_end) and today() <= self.trial_end
        return False


class PartnerClick(models.Model):
    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name="clicks")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_hash = models.CharField(max_length=32, blank=True, verbose_name="Empreinte IP")

    class Meta:
        verbose_name = "Clic sur le lien"
        verbose_name_plural = "Clics sur le lien"
        indexes = [models.Index(fields=["partner", "created_at"])]


class ReferralSource(models.TextChoices):
    LINK = "link", "Lien"
    CODE = "code", "Code saisi"
    MANUAL = "manual", "Manuel"


class Referral(models.Model):
    partner = models.ForeignKey(
        Partner, on_delete=models.PROTECT, related_name="referrals", verbose_name="Partenaire"
    )
    seller = models.OneToOneField(
        "accounts.SellerProfile",
        on_delete=models.PROTECT,
        related_name="referral",
        verbose_name="Vendeur inscrit via le lien",
    )
    attributed_at = models.DateTimeField(default=timezone.now, verbose_name="Attribué le")
    source = models.CharField(
        max_length=8, choices=ReferralSource.choices, default=ReferralSource.LINK
    )
    signup_ip_hash = models.CharField(max_length=32, blank=True)
    first_paid_at = models.DateTimeField(null=True, blank=True)
    commission_ends_at = models.DateTimeField(null=True, blank=True)
    flagged = models.BooleanField(default=False, db_index=True, verbose_name="Signalé")
    flag_reason = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "Inscription via le lien"
        verbose_name_plural = "Inscriptions via le lien"
        indexes = [
            models.Index(fields=["partner", "attributed_at"]),
            models.Index(fields=["partner", "signup_ip_hash", "attributed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.partner.code} -> vendeur {self.seller_id}"

    def save(self, *args, **kwargs):
        """Le parrain et le vendeur d'un parrainage ne changent jamais."""
        if self.pk:
            old = (
                Referral.objects.filter(pk=self.pk)
                .values("partner_id", "seller_id")
                .first()
            )
            if old and (old["partner_id"] != self.partner_id or old["seller_id"] != self.seller_id):
                raise ValidationError(
                    "Une inscription via le lien ne peut être ni réattribuée ni déplacée."
                )
        super().save(*args, **kwargs)


class CommissionStatus(models.TextChoices):
    PENDING = "pending", "À valider"
    VALIDATED = "validated", "Validée"
    PAID = "paid", "Versée"
    CANCELLED = "cancelled", "Annulée"


class PayoutStatus(models.TextChoices):
    DUE = "due", "À verser"
    PAID = "paid", "Versé"


class Payout(models.Model):
    partner = models.ForeignKey(
        Partner, on_delete=models.PROTECT, related_name="payouts", verbose_name="Partenaire"
    )
    period = models.CharField(max_length=7, verbose_name="Période", help_text="AAAA-MM")
    total_fcfa = models.PositiveIntegerField(verbose_name="Total (FCFA)")
    status = models.CharField(
        max_length=8, choices=PayoutStatus.choices, default=PayoutStatus.DUE, db_index=True
    )
    orange_reference = models.CharField(max_length=80, blank=True, verbose_name="Référence Orange")
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Versement"
        verbose_name_plural = "Versements"
        ordering = ["-period"]
        constraints = [
            models.UniqueConstraint(fields=["partner", "period"], name="payout_unique_partner_period"),
        ]

    def __str__(self) -> str:
        return f"{self.partner.code} {self.period} : {self.total_fcfa} FCFA"

    @property
    def due_date(self) -> date:
        """Échéance : le PARTNER_PAYOUT_DEADLINE_DAY du mois suivant la période."""
        year, month = (int(x) for x in self.period.split("-"))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return date(year, month, settings.PARTNER_PAYOUT_DEADLINE_DAY)


class CommissionEntry(models.Model):
    referral = models.ForeignKey(
        Referral,
        on_delete=models.PROTECT,
        related_name="commissions",
        verbose_name="Inscription via le lien",
    )
    payment = models.OneToOneField(
        "subscriptions.SubscriptionPayment",
        on_delete=models.PROTECT,
        related_name="partner_commission",
        verbose_name="Paiement d'abonnement",
    )
    gross_fcfa = models.PositiveIntegerField(verbose_name="Montant payé (FCFA)")
    net_fcfa = models.PositiveIntegerField(verbose_name="Net après retenue Orange (FCFA)")
    percent = models.PositiveSmallIntegerField(verbose_name="Commission (%)")
    commission_fcfa = models.PositiveIntegerField(verbose_name="Commission (FCFA)")
    status = models.CharField(
        max_length=10,
        choices=CommissionStatus.choices,
        default=CommissionStatus.PENDING,
        db_index=True,
        verbose_name="Statut",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    payout = models.ForeignKey(
        Payout, null=True, blank=True, on_delete=models.PROTECT, related_name="entries"
    )

    class Meta:
        verbose_name = "Commission"
        verbose_name_plural = "Commissions"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(commission_fcfa__lte=F("net_fcfa")) & Q(net_fcfa__lte=F("gross_fcfa")),
                name="commission_amounts_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["referral", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Commission {self.commission_fcfa} FCFA ({self.get_status_display()})"


# ── Documents, liens privés, journal des messages (bloc H) ────────────────────

class ImmutableQuerySet(models.QuerySet):
    """Refuse toute modification ou suppression en masse."""

    def update(self, **kwargs):
        raise ValidationError("Cet enregistrement est immuable : aucune modification possible.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Cet enregistrement est immuable : aucune modification possible.")

    def delete(self):
        raise ValidationError("Cet enregistrement est immuable : aucune suppression possible.")


ImmutableManager = models.Manager.from_queryset(ImmutableQuerySet)


class AccessLinkPurpose(models.TextChoices):
    VIEW = "view", "Consultation"
    ACCEPT = "accept", "Acceptation"


class PartnerAccessLink(models.Model):
    """Lien privé d'un partenaire. Le jeton en clair n'est JAMAIS stocké (empreinte SHA-256)."""

    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name="access_links")
    purpose = models.CharField(max_length=8, choices=AccessLinkPurpose.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    # Un jeton = une acceptation : renseigné une seule fois, à l'acceptation.
    acceptance = models.ForeignKey(
        "partners.PartnerAcceptance",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="access_links",
        verbose_name="Acceptation obtenue avec ce lien",
    )

    class Meta:
        verbose_name = "Lien privé"
        verbose_name_plural = "Liens privés"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Lien {self.get_purpose_display()} de {self.partner.code}"

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()


SEAL_MONTHS = ["JAN", "FÉV", "MAR", "AVR", "MAI", "JUN", "JUL", "AOÛ", "SEP", "OCT", "NOV", "DÉC"]


class AcceptanceDocType(models.TextChoices):
    TRIAL_LETTER = "trial_letter", "Lettre d'essai"
    PROGRAM_TERMS = "program_terms", "Conditions du programme partenaire"


class AcceptanceMethod(models.TextChoices):
    ONLINE = "online_checkbox", "En ligne (case cochée)"
    WRITTEN = "written_manual", "Écrite (saisie par l'équipe)"


class PartnerAcceptance(models.Model):
    """Preuve d'acceptation d'un document : IMMUABLE (ni mise à jour ni suppression)."""

    partner = models.ForeignKey(
        Partner, on_delete=models.PROTECT, related_name="acceptances", verbose_name="Partenaire"
    )
    doc_type = models.CharField(max_length=16, choices=AcceptanceDocType.choices, verbose_name="Document")
    doc_version = models.CharField(max_length=10, verbose_name="Version")
    text_snapshot = models.TextField(verbose_name="Texte accepté")
    text_sha256 = models.CharField(max_length=64, verbose_name="Empreinte du texte")
    signer_name = models.CharField(max_length=160, verbose_name="Nom saisi")
    accepted_at = models.DateTimeField(default=timezone.now, verbose_name="Accepté le")
    ip_hash = models.CharField(max_length=32, blank=True, verbose_name="Empreinte IP")
    method = models.CharField(
        max_length=16, choices=AcceptanceMethod.choices, default=AcceptanceMethod.ONLINE, verbose_name="Méthode"
    )
    manual_reference = models.CharField(max_length=200, blank=True, verbose_name="Référence de l'acceptation écrite")
    optional_consents = models.JSONField(default=dict, blank=True, verbose_name="Consentements facultatifs")

    objects = ImmutableManager()

    class Meta:
        verbose_name = "Acceptation de document"
        verbose_name_plural = "Acceptations de documents"
        ordering = ["-accepted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["partner", "doc_type", "doc_version"], name="acceptance_unique_doc_version"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.partner.code} : {self.get_doc_type_display()} v{self.doc_version}"

    @property
    def seal_date(self) -> str:
        """Date du sceau : JJ MMM AAAA en majuscules (heure UTC), ex. 09 OCT 2026."""
        d = self.accepted_at_utc
        return f"{d.day:02d} {SEAL_MONTHS[d.month - 1]} {d.year}"

    @property
    def is_invalidated(self) -> bool:
        return hasattr(self, "invalidation")

    @property
    def reference(self) -> str:
        """Référence imprimée : numéro d'acceptation + 12 premiers caractères de l'empreinte."""
        return f"{self.pk:06d}-{self.text_sha256[:12]}"

    @property
    def accepted_at_utc(self):
        from datetime import timezone as _tz

        return self.accepted_at.astimezone(_tz.utc)

    @property
    def cite_shop(self) -> bool | None:
        """Autorisation de citer la boutique (lettre d'essai seulement)."""
        if self.doc_type != AcceptanceDocType.TRIAL_LETTER:
            return None
        return bool((self.optional_consents or {}).get("cite_shop"))

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Une acceptation est immuable : aucune modification possible.")
        if self.method == AcceptanceMethod.WRITTEN and not (self.manual_reference or "").strip():
            raise ValidationError("Une acceptation écrite exige la référence du message ou du document.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Une acceptation est immuable : aucune suppression possible.")


class AcceptanceInvalidation(models.Model):
    """Invalidation d'une acceptation par l'équipe. Ne supprime ni ne modifie rien : elle s'ajoute.

    Le motif est interne (jamais affiché publiquement)."""

    acceptance = models.OneToOneField(
        PartnerAcceptance, on_delete=models.PROTECT, related_name="invalidation", verbose_name="Acceptation"
    )
    reason = models.TextField(verbose_name="Motif (interne)")
    invalidated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableManager()

    class Meta:
        verbose_name = "Invalidation d'acceptation"
        verbose_name_plural = "Invalidations d'acceptations"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Une invalidation est immuable : aucune modification possible.")
        if not (self.reason or "").strip():
            raise ValidationError("Indiquez le motif (interne) de l'invalidation.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Une invalidation est immuable : aucune suppression possible.")


class OutboundMessage(models.Model):
    """Journal des messages WhatsApp préparés par l'équipe. Jamais modifié."""

    partner = models.ForeignKey(
        Partner, null=True, blank=True, on_delete=models.PROTECT, related_name="messages"
    )
    phone_e164 = models.CharField(max_length=20, verbose_name="Numéro")
    template_key = models.CharField(max_length=30, verbose_name="Modèle")
    body_text = models.TextField(verbose_name="Message")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    opened_at = models.DateTimeField(default=timezone.now, verbose_name="Lien WhatsApp préparé le")

    objects = ImmutableManager()

    class Meta:
        verbose_name = "Message préparé"
        verbose_name_plural = "Messages préparés"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Le journal des messages n'est jamais modifié.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Le journal des messages n'est jamais supprimé.")
