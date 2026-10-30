"""Suivi des ventes d'articles importes (spec §5.4, §15.1, §15.2).

Regles qui ne se discutent pas :
- ce module LIT `orders` (jamais d'ecriture sur `Order`, `OrderItem` ni sur le stock) ;
- `not_delivered` n'est jamais ecrase par la synchronisation ;
- `paid_confirmed` n'est jamais retrograde, sauf l'unique exception « presomption renversee »
  (§15.1 regle 1) ; toute autre correction est faite par l'equipe, motivee, journalisee ;
- « Pas livre » ne touche NI la commande NI le stock : decision R1 du 24/10/2026 (le circuit
  d'annulation de la vendeuse est reserve a la boutique proprietaire et refuse des la mise
  en livraison, voir distrib/README.md § c).
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import audit
from distrib.models import (
    DistribCorrection,
    DistribSettlement,
    DistribStatement,
    ImportedProduct,
)
from distrib.services import commission as commission_service
from orders.models import Order, OrderItem, OrderStatus

logger = logging.getLogger(__name__)

S = DistribSettlement.Status

OPEN_STATUSES = (S.ORDERED, S.IN_DELIVERY, S.DELIVERED_BY_SHOP)
# Lignes sur lesquelles la cliente peut encore se manifester (code a 4 chiffres valable).
CUSTOMER_OPEN_STATUSES = OPEN_STATUSES + (S.NOT_DELIVERED,)

STATUS_MAP = {
    OrderStatus.PENDING: S.ORDERED,
    OrderStatus.CONFIRMED: S.ORDERED,
    OrderStatus.OUT_FOR_DELIVERY: S.IN_DELIVERY,
    OrderStatus.DELIVERED: S.DELIVERED_BY_SHOP,
    OrderStatus.CANCELLED: S.CANCELLED,
}
# Statuts de commande a partir desquels le delai de confirmation automatique court.
CONFIRMED_ORDER_STATUSES = (OrderStatus.CONFIRMED, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED)


# ── Signaux vers le pilotage ──────────────────────────────────────────────


def raise_signal(settlement: DistribSettlement, kind: str, **meta) -> None:
    """Signal au pilotage HayaFlash : trace dans l'AuditLog (jamais d'arbitrage dans l'outil)."""
    audit(
        f"distrib.signal.{kind}",
        entity_type="DistribSettlement",
        entity_id=settlement.pk,
        distributor_id=settlement.distributor_id,
        **meta,
    )


# ── Creation et synchronisation ───────────────────────────────────────────


def _new_receipt_code(customer_phone: str | None) -> str:
    """Code a 4 chiffres, distinct des autres lignes encore ouvertes de la meme cliente."""
    code = f"{secrets.randbelow(10000):04d}"
    for _ in range(20):
        taken = DistribSettlement.objects.filter(
            receipt_code=code,
            order__customer_phone=customer_phone,
            status__in=CUSTOMER_OPEN_STATUSES,
        ).exists()
        if not taken:
            return code
        code = f"{secrets.randbelow(10000):04d}"
    return code


def _create_line(order: Order, item: OrderItem, imported: ImportedProduct) -> DistribSettlement:
    invite = imported.invite
    sale = Decimal(item.price_snapshot) * item.quantity
    wholesale = Decimal(imported.wholesale_product.wholesale_price) * item.quantity
    return DistribSettlement.objects.create(
        distributor=invite.distributor,
        invite=invite,
        order=order,
        order_item=item,
        imported_product=imported,
        quantity=item.quantity,
        sale_amount=sale,
        wholesale_amount=wholesale,
        reseller_margin=sale - wholesale,
        receipt_code=_new_receipt_code(order.customer_phone),
    )


def recalc_statement(statement: DistribStatement) -> None:
    """Recalcule un releve `to_pay` apres retrait d'une ligne ; un releve vide disparait."""
    lines = list(statement.lines.all())
    if not lines:
        statement.delete()
        return
    statement.amount = sum((line.reseller_margin for line in lines), Decimal("0"))
    statement.line_count = len(lines)
    statement.save(update_fields=["amount", "line_count"])


def _reverse_presumption(line: DistribSettlement, now) -> None:
    """§15.1 regle 1 : commande annulee apres une confirmation AUTOMATIQUE, sans versement."""
    old = line.status
    statement = line.statement
    line.status = S.CANCELLED
    line.reseller_margin = Decimal("0")
    line.commission_amount = Decimal("0")
    line.commission_billable = False
    line.statement = None
    line.conflict_flag = False
    line.save()
    DistribCorrection.objects.create(
        settlement=line,
        old_status=old,
        new_status=S.CANCELLED,
        reason="Commande annulée après confirmation automatique",
        author=None,
    )
    if statement is not None:
        recalc_statement(statement)


def _apply_order_state(line: DistribSettlement, order: Order, now) -> None:
    """Aligne une ligne sur l'etat de sa commande, en respectant les statuts definitifs."""
    if line.status == S.NOT_DELIVERED:
        return
    if line.status == S.PAID_CONFIRMED:
        if order.status == OrderStatus.CANCELLED:
            if line.confirmation_source == DistribSettlement.ConfirmationSource.AUTO and line.payout_id is None:
                _reverse_presumption(line, now)
            elif not line.conflict_flag:
                line.conflict_flag = True
                line.save(update_fields=["conflict_flag", "updated_at"])
                raise_signal(line, "cancelled_after_confirmation", source=line.confirmation_source)
        return
    if line.status == S.CANCELLED:
        return

    changed = []
    if line.confirmed_at is None and order.status in CONFIRMED_ORDER_STATUSES:
        line.confirmed_at = now
        line.auto_confirm_at = now + timedelta(hours=line.distributor.auto_confirm_hours)
        changed += ["confirmed_at", "auto_confirm_at"]
    new_status = STATUS_MAP[order.status]
    if new_status != line.status:
        line.status = new_status
        changed.append("status")
        if new_status == S.CANCELLED:
            line.commission_amount = Decimal("0")
            line.commission_billable = False
            changed += ["commission_amount", "commission_billable"]
    if changed:
        line.save(update_fields=changed + ["updated_at"])


def sync_order(order_id: int) -> int:
    """Cree les lignes manquantes et aligne les statuts pour une commande. Retourne le nombre
    de lignes de suivi concernees. Idempotent (rejouable sans effet)."""
    now = timezone.now()
    touched = 0
    with transaction.atomic():
        order = Order.service_objects.filter(pk=order_id).first()
        if order is None:
            return 0
        items = list(order.items.all())
        imports = {
            i.product_id: i
            for i in ImportedProduct.objects.filter(product_id__in=[it.product_id for it in items])
            .select_related("invite__distributor", "wholesale_product")
        }
        for item in items:
            imported = imports.get(item.product_id)
            if imported is None:
                continue
            line = DistribSettlement.objects.select_for_update().filter(order_item=item).first()
            if line is None:
                try:
                    with transaction.atomic():
                        line = _create_line(order, item, imported)
                except IntegrityError:  # course avec la reconciliation : la ligne existe deja
                    line = DistribSettlement.objects.select_for_update().get(order_item=item)
            _apply_order_state(line, order, now)
            touched += 1
    return touched


def safe_sync_order(order_id: int) -> None:
    """Point d'entree du signal : toute erreur est journalisee, JAMAIS propagee (§2.4)."""
    try:
        sync_order(order_id)
    except Exception:
        logger.exception("distrib: synchronisation de la commande %s en echec (la reconciliation reessaiera)", order_id)


def reconcile() -> int:
    """Rattrape les oublis du signal : lignes manquantes et statuts a aligner. Retourne le
    nombre de commandes traitees. Erreur sur une commande = journalisee, les autres continuent."""
    from django.db.models import Q

    item_filter = Q(product__distrib_import__isnull=False) & (
        Q(distrib_settlements__isnull=True)
        | Q(distrib_settlements__status__in=OPEN_STATUSES)
        | Q(distrib_settlements__status=S.PAID_CONFIRMED, order__status=OrderStatus.CANCELLED)
    )
    order_ids = list(
        OrderItem.objects.filter(item_filter).values_list("order_id", flat=True).distinct()
    )
    for order_id in order_ids:
        safe_sync_order(order_id)
    return len(order_ids)


# ── Confirmation de livraison et de paiement ──────────────────────────────


def _mark_paid(line: DistribSettlement, *, source: str, by, at) -> None:
    amount, billable = commission_service.commission_for(
        line.distributor, line.sale_amount, timezone.localtime(at).date()
    )
    line.status = S.PAID_CONFIRMED
    line.paid_confirmed_at = at
    line.paid_confirmed_by = by
    line.confirmation_source = source
    line.commission_amount = amount
    line.commission_billable = billable
    line.save()


def confirm_paid(line: DistribSettlement, *, source: str, by=None, at=None) -> tuple[DistribSettlement, bool]:
    """Passe la ligne a `paid_confirmed` (livree = payee). Retourne `(ligne, changee ?)`.

    Idempotent. Refuse une ligne annulee ou declaree non livree : ce dernier cas passe par la
    correction de l'equipe (ou, cote cliente, par `customer_confirm`)."""
    with transaction.atomic():
        locked = DistribSettlement.objects.select_for_update().select_related("distributor", "order").get(pk=line.pk)
        if locked.status == S.PAID_CONFIRMED:
            return locked, False
        if locked.status == S.CANCELLED or locked.order.status == OrderStatus.CANCELLED:
            raise ValidationError("Cette commande est annulée : elle ne peut pas être confirmée.")
        if locked.status == S.NOT_DELIVERED:
            raise ValidationError("Cette ligne est déclarée « Pas livré » : seule l'équipe HayaFlash peut la corriger.")
        _mark_paid(locked, source=source, by=by, at=at or timezone.now())
    return locked, True


def distributor_confirm(line: DistribSettlement, user) -> tuple[DistribSettlement, bool]:
    """« Livré et payé » : le grossiste confirme plus tot que la presomption. Proprietaire seulement."""
    if line.distributor.user_id != user.pk:
        raise PermissionDenied
    return confirm_paid(line, source=DistribSettlement.ConfirmationSource.DISTRIBUTOR, by=user)


def auto_confirm_due(now=None) -> int:
    """Presomption de livraison (§15.1) : confirme les lignes dont l'echeance est passee.

    Idempotent, verrouille, jamais propage d'erreur d'une ligne aux autres. Retourne le nombre
    de lignes confirmees."""
    now = now or timezone.now()
    ids = list(
        DistribSettlement.objects.filter(
            status__in=OPEN_STATUSES, auto_confirm_at__isnull=False, auto_confirm_at__lte=now
        ).values_list("pk", flat=True)
    )
    done = 0
    for pk in ids:
        try:
            with transaction.atomic():
                line = (
                    DistribSettlement.objects.select_for_update()
                    .select_related("distributor", "order")
                    .get(pk=pk)
                )
                if line.status not in OPEN_STATUSES or line.auto_confirm_at is None or line.auto_confirm_at > now:
                    continue
                if line.order.status == OrderStatus.CANCELLED:
                    continue  # la synchronisation l'annulera ; jamais de presomption sur une commande annulee
                _mark_paid(line, source=DistribSettlement.ConfirmationSource.AUTO, by=None, at=now)
                done += 1
        except Exception:
            logger.exception("distrib: confirmation automatique de la ligne %s en echec", pk)
    return done


# ── « Pas livre » ─────────────────────────────────────────────────────────


def declare_not_delivered(line: DistribSettlement, user, *, reason: str, note: str = "") -> DistribSettlement:
    """Declaration de non-livraison par le grossiste (§15.2, decision R1).

    Ecrit UNIQUEMENT dans `DistribSettlement` : ni `Order`, ni `OrderItem`, ni stock, ni mouvement
    de stock, et aucun appel a un circuit d'annulation. Refusee apres `paid_confirmed`."""
    if line.distributor.user_id != user.pk:
        raise PermissionDenied
    reasons = {value for value, _ in DistribSettlement.NotDeliveredReason.choices}
    if reason not in reasons:
        raise ValidationError("Choisissez un motif.")
    note = (note or "").strip()[:200]
    if reason == DistribSettlement.NotDeliveredReason.OTHER and not note:
        raise ValidationError("Précisez le motif en quelques mots.")
    with transaction.atomic():
        locked = DistribSettlement.objects.select_for_update().get(pk=line.pk)
        if locked.status == S.PAID_CONFIRMED:
            raise ValidationError("Trop tard : la livraison est déjà confirmée. Contactez l'équipe HayaFlash.")
        if locked.status == S.CANCELLED:
            raise ValidationError("Cette commande est annulée.")
        if locked.status == S.NOT_DELIVERED:
            raise ValidationError("Cette ligne est déjà déclarée « Pas livré ».")
        locked.status = S.NOT_DELIVERED
        locked.not_delivered_reason = reason
        locked.not_delivered_note = note
        locked.declared_by = user
        locked.declared_at = timezone.now()
        locked.save()
        audit(
            "distrib.not_delivered",
            entity_type="DistribSettlement",
            entity_id=locked.pk,
            actor=user,
            reason=reason,
        )
    return locked


# ── Correction par l'equipe ───────────────────────────────────────────────

CORRECTABLE_TO = (S.PAID_CONFIRMED, S.CANCELLED, S.NOT_DELIVERED, S.ORDERED)


def staff_correct(line: DistribSettlement, user, *, new_status: str, reason: str) -> DistribSettlement:
    """Correction d'une ligne par l'EQUIPE uniquement, motivee et journalisee (`DistribCorrection`).

    Une ligne deja rattachee a un versement n'est pas modifiable : rouvrir d'abord le releve."""
    if not getattr(user, "is_staff", False):
        raise PermissionDenied
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Le motif est obligatoire.")
    if new_status not in CORRECTABLE_TO:
        raise ValidationError("Statut non autorisé pour une correction.")
    with transaction.atomic():
        locked = (
            DistribSettlement.objects.select_for_update(of=("self",))
            .select_related("distributor", "statement")
            .get(pk=line.pk)
        )
        if locked.payout_id is not None:
            raise ValidationError("Cette ligne fait partie d'un versement : rouvrez d'abord le relevé.")
        old = locked.status
        if old == new_status:
            raise ValidationError("La ligne est déjà dans ce statut.")
        statement = locked.statement
        if new_status == S.PAID_CONFIRMED:
            now = timezone.now()
            _mark_paid(locked, source="", by=user, at=now)
        else:
            locked.status = new_status
            locked.paid_confirmed_at = None
            locked.paid_confirmed_by = None
            locked.confirmation_source = ""
            locked.commission_amount = Decimal("0")
            locked.commission_billable = False
            locked.statement = None
            if new_status == S.CANCELLED:
                locked.reseller_margin = Decimal("0")
        locked.conflict_flag = False
        locked.save()
        if statement is not None and locked.statement_id is None:
            recalc_statement(statement)
        DistribCorrection.objects.create(
            settlement=locked, old_status=old, new_status=new_status, reason=reason, author=user
        )
        audit("distrib.correction", entity_type="DistribSettlement", entity_id=locked.pk, actor=user,
              old=old, new=new_status)
    return locked
