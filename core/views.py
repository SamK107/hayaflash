from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from accounts.models import SellerProfile
from accounts.services.users import get_user_by_phone
from core.legal import (
    LEGAL_ACCEPTANCE_REQUIRED_MESSAGE,
    LEGAL_CGU_VERSION,
    LEGAL_LAST_UPDATED,
    LEGAL_PRIVACY_VERSION,
    record_legal_acceptances,
)
from core.services import honeypot, rate_limit
from core.services.rate_limit import LOGIN_RATE_LIMIT_MESSAGE, REGISTER_RATE_LIMIT_MESSAGE
from core.services.client_ip import get_client_ip

logger = logging.getLogger(__name__)

REGISTER_FAILED_MESSAGE = (
    "Impossible de créer le compte pour le moment. Réessayez dans quelques instants."
)

# Limites de debit (valeurs : settings.RATELIMIT_*, core/services/rate_limit.py, fail-open).
# Le verrou par telephone + IP (5 echecs / 30 min) est gere par django-axes
# (config/settings/base.py, AXES_*) : pas de verrou "telephone seul" ici, sinon
# n'importe qui bloquerait un vendeur en pleine vente.

# Inscription : limite par IP (settings.RATELIMIT_REGISTER_IP) + honeypot signe
# (core/services/honeypot.py : champ piege + horodatage signe, erreur generique).

# ── helpers ────────────────────────────────────────────────────────────────


def _normalize(raw: str) -> str:
    """Normalize phone: strip spaces, ensure leading +."""
    phone = raw.strip().replace(" ", "").replace("-", "")
    if phone and not phone.startswith("+"):
        # assume Mali (+223) if no country code and starts with 0 or 7/6/9
        if phone.startswith("0"):
            phone = "+223" + phone[1:]
        else:
            phone = "+223" + phone
    return phone


def _phone_errors(
    phone: str, password: str, password2: str, business_name: str
) -> list[str]:
    from django.contrib.auth import get_user_model

    from accounts.services.passwords import password_policy_errors

    errs = []
    if not phone:
        errs.append("Le numéro de téléphone est obligatoire.")
    if not business_name.strip():
        errs.append("Le nom de votre boutique est obligatoire.")
    # F-17 : validateurs Django (8 caracteres minimum, mot de passe courant,
    # tout numerique, similarite avec le numero / le nom de la boutique).
    errs.extend(
        password_policy_errors(
            password,
            get_user_model()(phone=phone, display_name=business_name),
        )
    )
    if password != password2:
        errs.append("Les deux mots de passe ne correspondent pas.")
    return errs


# ── views ──────────────────────────────────────────────────────────────────


def home(request):
    # La page marketing est accessible à tous (vendeur connecté ou simple visiteur).
    # Le template adapte la navbar selon l'état d'authentification.
    return render(request, "core/home.html")


def _post_login_redirect_target(user) -> str:
    """
    Route par defaut apres connexion : la plupart des comptes sont des
    vendeurs (SellerProfile), mais un compte staff cree via createsuperuser
    (ou tout futur compte non-vendeur) n'en a pas. Sans ce garde-fou,
    seller_home_view plante en 500 (RelatedObjectDoesNotExist) des la
    redirection post-connexion — decouvert en auditant la connexion d'un
    compte staff (voir Phase 10.0).
    """
    if not SellerProfile.objects.filter(user=user).exists():
        return "platform_admin" if user.is_staff else "seller_home"
    return "seller_home"


def _safe_next_url(request) -> str | None:
    """`?next=` valide ou None (F-06 : pas de redirection ouverte).

    Seul l'hote de la requete (deja controle contre ALLOWED_HOSTS par Django)
    est accepte ; en HTTPS, une cible http:// est refusee. Les URLs externes,
    `//hote`, `javascript:` et les variantes avec antislash sont ignorees : on
    retombe alors sur la page par defaut.
    """
    candidate = request.GET.get("next", "")
    # Antislash refuse d'emblee (les navigateurs le lisent comme « / ») ; seuls
    # un chemin absolu « /... » ou une URL http(s) complete sont consideres.
    if "\\" in candidate or not candidate.startswith(("/", "http://", "https://")):
        return None
    if url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return None


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_post_login_redirect_target(request.user))

    error = None

    if request.method == "POST":
        raw_phone = request.POST.get("phone", "").strip()
        password = request.POST.get("password", "")

        if rate_limit.login_ip_limited(request):
            return render(
                request,
                "accounts/login.html",
                {"error": LOGIN_RATE_LIMIT_MESSAGE},
                status=429,
            )

        if not raw_phone or not password:
            error = "Veuillez renseigner votre téléphone et votre mot de passe."
        else:
            phone = _normalize(raw_phone)
            user = authenticate(request, username=phone, password=password)
            if user is not None:
                login(request, user)
                return redirect(_safe_next_url(request) or _post_login_redirect_target(user))
            else:
                error = "Numéro de téléphone ou mot de passe incorrect."

    return render(request, "accounts/login.html", {"error": error})


def register_view(request):
    if request.user.is_authenticated:
        return redirect("seller_home")

    errors = []
    form_data = {}

    if request.method == "POST":
        raw_phone = request.POST.get("phone", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        business_name = request.POST.get("business_name", "").strip()
        accept_terms = bool(request.POST.get("accept_terms"))

        form_data = {
            "phone": raw_phone,
            "business_name": business_name,
            "accept_terms": accept_terms,
        }

        ip = get_client_ip(request)
        if rate_limit.register_ip_limited(request):
            return render(
                request,
                "accounts/register.html",
                {"errors": [REGISTER_RATE_LIMIT_MESSAGE], "form_data": form_data},
                status=429,
            )

        reason = honeypot.rejection_reason(request.POST)
        if reason:
            logger.info("Inscription bloquee par le honeypot (%s, ip=%s).", reason, ip)
            return render(
                request,
                "accounts/register.html",
                {"errors": [honeypot.GENERIC_ERROR], "form_data": form_data},
            )

        phone = _normalize(raw_phone)
        errors = _phone_errors(phone, password, password2, business_name)
        if not accept_terms:
            errors.append(LEGAL_ACCEPTANCE_REQUIRED_MESSAGE)

        if not errors:
            # verifier unicite du numero
            if get_user_by_phone(phone):
                errors.append(
                    "Ce numéro est déjà utilisé. Connectez-vous ou utilisez un autre numéro."
                )

        if not errors:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        phone=phone,
                        password=password,
                        display_name=business_name,
                    )
                    SellerProfile.objects.create(
                        user=user,
                        business_name=business_name,
                    )
                    record_legal_acceptances(user, request)
                login(request, user, backend="accounts.backends.PhoneAuthBackend")
                messages.success(
                    request, f"Bienvenue ! Votre boutique '{business_name}' est prete."
                )
                return redirect("seller_home")
            except Exception as exc:
                # F-18 : jamais le texte brut de l'exception a l'utilisateur. Le
                # journal garde le type et une empreinte du numero (jamais le
                # numero ni le mot de passe ; le message d'exception peut les
                # contenir, il n'est donc pas journalise).
                logger.error(
                    "Inscription echouee (%s) %s",
                    type(exc).__name__,
                    rate_limit.phone_key("register", phone),
                )
                errors.append(REGISTER_FAILED_MESSAGE)

    return render(
        request,
        "accounts/register.html",
        {
            "errors": errors,
            "form_data": form_data,
        },
    )


def logout_view(request):
    if request.method == "POST":
        logout(request)
    return redirect("login")


@login_required
def seller_home_view(request):
    from django.utils import timezone

    from flash_sales.models import FlashSale, FlashSaleStatus
    from flash_sales.services.ordering import live_now_q, upcoming_q
    from orders.models import Order, OrderStatus

    # Garde-fou : un compte sans SellerProfile (staff createsuperuser, lien
    # /seller/ favori/partage par erreur) plantait ici en 500. Staff ->
    # /platform-admin/. Autres comptes : page explicative -- l'ancienne
    # redirection vers /login/ bouclait (login renvoie un compte connecte vers
    # /seller/). Cible des redirections de accounts.access.seller_required.
    seller = getattr(request.user, "seller_profile", None)
    if seller is None:
        if request.user.is_staff:
            return redirect("platform_admin")
        return render(request, "seller/no_profile.html")

    # Par l'heure (comme les pages publiques) : une vente dont l'heure de fin
    # est passee n'est plus "a venir / en cours", meme si Celery ne l'a pas
    # encore fermee.
    now = timezone.now()
    active_qs = FlashSale.objects.filter(
        live_now_q(now) | upcoming_q(now), owner=seller
    )
    recent_qs = (
        FlashSale.objects.filter(owner=seller)
        .exclude(live_now_q(now) | upcoming_q(now))
        .exclude(status=FlashSaleStatus.CANCELLED)
    )
    # F-75 : les cartes affichent le vrai total (COUNT), pas la taille de la
    # liste tranchee ci-dessous ([:5] / [:3]).
    active_total = active_qs.count()
    recent_total = recent_qs.count()
    active_sales = active_qs.order_by("start_time")[:5]
    recent_sales = recent_qs.order_by("-start_time")[:3]

    total_orders = Order.objects.filter(flash_sale__owner=seller).count()
    # Ligne d'etat de l'en-tete. « En cours » = par l'heure (point 15) ;
    # « a traiter » = statut pending uniquement (meme definition que la pastille
    # « Commandes » de la navigation, core/context_processors.py).
    live_count = FlashSale.objects.filter(live_now_q(now), owner=seller).count()
    to_process_count = Order.service_objects.filter(
        flash_sale__owner=seller, status=OrderStatus.PENDING
    ).count()

    return render(
        request,
        "seller/home.html",
        {
            "active_sales": active_sales,
            "recent_sales": recent_sales,
            "active_total": active_total,
            "recent_total": recent_total,
            "total_orders": total_orders,
            "live_count": live_count,
            "to_process_count": to_process_count,
            "seller_initials": _initials(request.user.display_name),
            "seller_first_name": (request.user.display_name or "").split(" ")[0],
        },
    )


def _initials(display_name: str) -> str:
    """Deux lettres pour la pastille de l'en-tete (« Awa Traore » -> « AT »)."""
    words = (display_name or "").split()
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    if words:
        return words[0][:2].upper()
    return "HF"


@staff_member_required
def platform_admin_dashboard(request):
    """Tableau de bord de pilotage HayaFlash (staff only, compte unique proprietaire)."""
    from datetime import timedelta

    from django.db.models import Count, Sum
    from django.utils import timezone

    from flash_sales.models import FlashSale
    from flash_sales.services.ordering import live_now_q
    from orders.models import Order
    from subscriptions.models import Subscription, SubscriptionPayment
    from subscriptions.services.platform_reporting import (
        get_orange_remittance_summary,
        get_revenue_breakdown,
        get_subscribed_sellers,
        get_subscription_revenue_timeline_monthly,
        get_subscription_revenue_ytd,
        revenue_payments,
    )

    now = timezone.now()
    month_start = now - timedelta(days=30)

    context = {
        "total_sellers": SellerProfile.objects.filter(is_active=True).count(),
        "subs_by_plan": (
            Subscription.objects.values("plan")
            .annotate(count=Count("id"))
            .order_by("plan")
        ),
        "live_sales": FlashSale.objects.filter(live_now_q()).count(),
        "total_orders_month": Order.service_objects.filter(
            created_at__gte=month_start
        ).count(),
        # CA = paiements reussis hors tests de paiement (tarif special "test").
        "mrr": (
            revenue_payments()
            .filter(paid_at__gte=month_start)
            .aggregate(total=Sum("amount"))["total"]
            or 0
        ),
        "total_revenue": (
            revenue_payments().aggregate(total=Sum("amount"))["total"] or 0
        ),
        "revenue_breakdown_30d": get_revenue_breakdown(since=month_start),
        "revenue_breakdown_all": get_revenue_breakdown(),
        "revenue_ytd": get_subscription_revenue_ytd(),
        # Serialise dans le template via |json_script (CSP : pas de JS inline).
        "revenue_timeline": get_subscription_revenue_timeline_monthly(),
        "orange": get_orange_remittance_summary(),
        "subscribed_sellers": get_subscribed_sellers(),
        "recent_payments": (
            SubscriptionPayment.objects.select_related("seller__user").order_by(
                "-created_at"
            )[:20]
        ),
    }
    return render(request, "core/platform_admin.html", context)


def _legal_context() -> dict:
    return {
        "cgu_version": LEGAL_CGU_VERSION,
        "privacy_version": LEGAL_PRIVACY_VERSION,
        "legal_last_updated": LEGAL_LAST_UPDATED,
    }


def legal_privacy(request):
    return render(request, "core/legal/privacy.html", _legal_context())


def legal_terms(request):
    from subscriptions.services.plans import get_duration_days

    context = _legal_context()
    context["plan_durations"] = {
        plan: get_duration_days(plan) for plan in ("medium", "pro")
    }
    return render(request, "core/legal/terms.html", context)


def legal_notice(request):
    return render(request, "core/legal/notice.html", _legal_context())


def service_worker(request):
    """
    Sert le service worker a la RACINE (/sw.js).

    Un SW servi depuis /static/sw.js n'a pour portee que /static/ : il ne
    controle aucune page, donc ni le mode hors ligne ni les criteres
    d'installabilite PWA de Chrome (bandeau "Installer" jamais propose).
    """
    from pathlib import Path

    from django.conf import settings
    from django.contrib.staticfiles import finders
    from django.http import Http404, HttpResponse

    path = finders.find("sw.js")
    # Repli : collectstatic (prod) puis source du depot (settings de test,
    # STATICFILES_DIRS vide et pas de collectstatic).
    for base in (settings.STATIC_ROOT, Path(settings.BASE_DIR) / "static"):
        if path or not base:
            break
        candidate = Path(base) / "sw.js"
        path = str(candidate) if candidate.exists() else None
    if not path:
        raise Http404("sw.js introuvable")
    with open(path, "rb") as fh:
        body = fh.read()
    response = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    # Le navigateur doit toujours revalider le SW pour recevoir les mises a jour.
    response["Cache-Control"] = "no-cache"
    return response
