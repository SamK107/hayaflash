# Proposition — émojis-icônes → pastilles Lucide (PR 3)

- **Date** : 2026-10-03 · **Branche** : `fix/icones-fcfa-ui` · **Statut** : ⏸ en attente de validation (aucun gabarit modifié)
- **Base** : section B du rapport `ui-audit-20261003.md` (branche `audit/ui-text-currency`), corrigée par la recherche des émojis de devise ci-dessous.

## 0. Correction du rapport : émojis de devise

La section C cherchait des caractères (`$ € £`), pas des émojis. Recherche de `💵 💰 💸 💴 💶 💷 🪙 💳 🤑` dans tout le dépôt (hors `.venv`, `static/vendor`, `Claude outputs`) :

| Fichier:ligne | Émoji | Nature | Traitement |
|---|---|---|---|
| `templates/core/home.html:640` | 💵 | icône UI (billet de **dollar**) | → `banknote` |
| `templates/core/home.html:570` | 💰 | icône UI (sac d'argent, symbole `$`) | → `wallet` |
| `templates/core/home.html:376` | 💸 | icône UI (billet avec ailes) | → `hand-coins` |
| `docs/workflows/WORKFLOW_P5_NOTIFS_SUBS.md:74` | 💰 | extrait de code dans une **doc** | hors périmètre (jamais vu d'un utilisateur) — signalé |
| `docs/PROJECT_SPEC.md:283` | 💰 | titre de doc | hors périmètre — signalé |

`💴 💶 💷 🪙 💳 🤑` : **0 occurrence**. `banknote`, `hand-coins` et `wallet` ne portent aucun symbole `$`/`€` (le pictogramme `banknote` est déjà utilisé dans `delivery_summary.html` et `orders/partials/kpi.html`).

Un garde-fou de test interdira `💵 💰 💸 💴 💶 💷 🪙` dans `templates/` et `static/js/` (implémenté en section 3 de la mission).

## 1. Les 36 émojis-icônes UI → Lucide 0.462.0

Tous les noms ont été vérifiés dans `static/vendor/lucide/lucide-0.462.0.min.js` (export `a.<NomPascal>=` présent). `Motorbike` **n'existe pas** dans cette version → `bike` pour 🛵/🏍️. Décompte : **10 hors home + 26 dans home.html** (le rapport annonçait 27 ; `home.html:783/803/823` sont des ★ et restent).

Colonne **Forme** : **B** = pastille `.hf-icon-badge` (bloc de présentation) ; **I** = icône inline `.hf-icon-inline` (1em, `currentColor`, sans fond) — l'émoji est dans une ligne de texte, un bouton ou une surimpression, une pastille de 40 px y serait disproportionnée.

| # | Fichier:ligne | Émoji | Fonction | Lucide | Forme | Couleur |
|---|---|---|---|---|---|---|
| 1 | `accounts/profile.html:58` | 📍 | zones de livraison du vendeur | `map-pin` | I | currentColor |
| 2 | `accounts/register.html:130` | ⚡ | bouton « Créer mon compte » | `zap` | I | currentColor |
| 3 | `accounts/settings.html:47` | ✨ | titre « Plan Pro » | `sparkles` | I | currentColor |
| 4 | `accounts/settings.html:95` | 🚀 | « Débloquez le Plan Pro » | `rocket` | I | currentColor |
| 5 | `analytics/flash_sale_public.html:130` | ⚡ | teaser avant ouverture | `zap` | I | currentColor |
| 6 | `analytics/flash_sale_public.html:287` | 🔥 | badge « vente en cours » | `flame` | I | currentColor |
| 7 | `analytics/flash_sale_public.html:302` | 🔍 | surimpression « zoom » sur photo | `zoom-in` | I | blanc |
| 8 | `analytics/flash_sale_public.html:349` | 🔍 | idem | `zoom-in` | I | blanc |
| 9 | `analytics/flash_sale_public.html:577` | 🎤 | « Votre message vocal » | `mic` | I | currentColor |
| 10 | `flash_sales/create.html:348` | ⚡ | bouton « Programmer la vente » | `zap` | I | currentColor |
| 11 | `core/home.html:344` | 📓 | problème : cahier | `notebook` | B | ardoise |
| 12 | `core/home.html:352` | 📱 | problème : 2ᵉ téléphone | `smartphone` | B | ardoise |
| 13 | `core/home.html:360` | 💬 | problème : commandes dans les DM | `message-circle` | B | ardoise |
| 14 | `core/home.html:368` | 📦 | problème : produit promis 3 fois | `package` | B | ardoise |
| 15 | `core/home.html:376` | 💸 | problème : gains inconnus | `hand-coins` | B | ardoise |
| 16 | `core/home.html:384` | 🚚 | problème : livraisons | `truck` | B | ardoise |
| 17 | `core/home.html:442` | ⏱️ | étape 1 : programmer | `timer` | B (rond existant `.step-i`) | violet |
| 18 | `core/home.html:455` | 📥 | étape 2 : commandes en direct | `inbox` | B | violet |
| 19 | `core/home.html:468` | 🛵 | étape 3 : livrer | `bike` | B | teal |
| 20 | `core/home.html:481` | 📊 | étape 4 : chiffres | `bar-chart-3` | B | bleu |
| 21 | `core/home.html:531` | ⏱️ | carte « Programmez en 30 s » | `timer` | B | violet |
| 22 | `core/home.html:544` | 📥 | carte « Commandes en direct » | `inbox` | B | violet |
| 23 | `core/home.html:557` | 🚚 | carte « Livraison sous contrôle » | `truck` | B | teal |
| 24 | `core/home.html:570` | 💰 | carte « Payé à la réception » | `wallet` | B | vert |
| 25 | `core/home.html:583` | 📊 | carte « Pilotage en temps réel » | `bar-chart-3` | B | bleu |
| 26 | `core/home.html:596` | 🔔 | carte « Clients fidélisés » | `bell` | B | ambre |
| 27 | `core/home.html:632` | ⏳ | bénéfice : temps | `hourglass` | B | violet |
| 28 | `core/home.html:640` | 💵 | bénéfice : argent retrouvé | `banknote` | B | vert |
| 29 | `core/home.html:648` | 🧠 | bénéfice : clarté | `brain` | B | ardoise |
| 30 | `core/home.html:656` | 🤝 | bénéfice : confiance client | `handshake` | B | ardoise |
| 31 | `core/home.html:664` | 📈 | bénéfice : croissance | `trending-up` | B | bleu |
| 32 | `core/home.html:674` | 💡 | « le vrai coût… » | `lightbulb` | B | ambre |
| 33 | `core/home.html:729` | 📲 | « Créez votre compte » | `smartphone-nfc` | B | violet |
| 34 | `core/home.html:734` | ⚡ | « Lancez une vente flash » | `zap` | B | violet |
| 35 | `core/home.html:739` | 🏍️ | « Votre livreur livre » | `bike` | B | teal |
| 36 | `core/home.html:980` | ⚡ | mini-étiquette (0,55 rem) | `zap` | I | currentColor |

## 2. Palette des pastilles (icône blanche)

Douce et sobre : aucun rouge/orange saturé (le `#FF4D2E` et le `#5B2EFF` de la landing, très saturés, ne sont **pas** repris tels quels). Ratios WCAG calculés (blanc `#FFF` sur fond) — seuil visé ≥ 3:1 pour un pictogramme.

| Variante | Hex | Thème | Ratio blanc/fond |
|---|---|---|---|
| `violet` | `#6556D6` | ventes flash, temps, lancement (violet de marque désaturé) | **5,45** |
| `teal` | `#0F857A` | livraison, logistique | **4,51** |
| `green` | `#1E8A4C` | paiement, argent (le `success #22C55E` ne passe pas : 2,3:1) | **4,38** |
| `blue` | `#2F6BD8` | statistiques, pilotage | **4,98** |
| `amber` | `#A5660B` | notifications, idées (le jaune de marque `#FFB800` est inutilisable avec du blanc) | **4,66** |
| `slate` | `#475569` | problèmes, conseils, relation humaine | **7,58** |

Toutes ≥ 4,3:1 (donc ≥ 3:1). Sur la landing sombre (`#1A1A2E`), chaque fond de pastille est nettement plus clair que le fond de page : lisible.

## 3. Composant

```css
.hf-icon-badge{display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;
  width:40px;height:40px;border-radius:12px;color:#fff;background:var(--hf-badge,#475569)}
.hf-icon-badge svg{width:20px;height:20px;stroke:currentColor}
.hf-icon-badge--lg{width:48px;height:48px;border-radius:14px}   /* landing : taille actuelle de .icon-r/.icon-v (3rem) */
.hf-icon-badge--lg svg{width:24px;height:24px}
.hf-icon-badge--violet{--hf-badge:#6556D6}  /* --teal #0F857A, --green #1E8A4C, --blue #2F6BD8, --amber #A5660B, --slate #475569 */
.hf-icon-inline{display:inline-block;width:1em;height:1em;vertical-align:-.125em;stroke:currentColor}
```

- **Où** : bloc `<style>` de `templates/base.html` (déjà présent ; `home.html` fait `extends "base.html"`) — pas de nouveau fichier ni de requête en plus. `home.html` supprimera son `.icon-r/.icon-v` devenu inutile ; le `.step-i` rond est conservé, seul son contenu change.
- **Tailwind / FV-01** : **aucune nouvelle classe Tailwind**. Tout est en CSS dédié (`hf-icon-*`), dimensions des `<svg>` comprises. **Aucune reconstruction de `tailwind-hayaflash.css`.** CSP : `style-src` n'est pas restreint (seul `script-src` l'est) et `base.html` a déjà un `<style>` inline.
- **Init** : `hf-base.js:67-71` appelle déjà `lucide.createIcons()` au `DOMContentLoaded` et après chaque `htmx:afterSwap`. Les 36 émojis visés sont dans du HTML statique rendu serveur (rien d'injecté par Alpine/HTMX), donc **aucun nouvel appel** n'est nécessaire.
- **A11y** : `aria-hidden="true"` sur chaque `<i data-lucide>` décoratif (le texte voisin porte le sens).
- Landing : on garde l'effet hover actuel (`scale/rotate`) via `.card:hover .hf-icon-badge`.

## 4. Glyphes ✓ ✕ ★

Laissés tels quels (typographie) : `hf-base.js:89,120`, `hf-install.js`, `profile.html:128`, `settings.html:121`, `flash_sale_public.html:221,693`, `sale_ended.html:125`, `delivery_row.html:41`, `home.html:783,803,823`.

## 5. Laissés tels quels (légitimes dans un message / une phrase)

- Textes de partage WhatsApp/Web Share : `🔥` (`flash_sale_public.html:430`, `share_links.py:93`), `⚡` (`flash_sale_public.html:185`, `seller_public.html:112`).
- Décors dans une phrase : `🙏` (`flash_sale_public.html:657`, `sale_ended.html:82`), `⏱` (`home.html:298`), `👋` (`seller/home.html:11`), `⚠️` (`subscriptions/admin.py:128`, admin Django).

## 6. Questions à trancher

1. OK pour la palette (6 couleurs) et le rendu **inline** (sans pastille) pour les 10 émojis situés dans du texte, un bouton ou une surimpression ?
2. Landing : pastilles 48 px (`--lg`) pour conserver la taille actuelle des blocs, plutôt que 40 px ?
3. Les 2 mentions de 💰 dans `docs/` : on laisse (hors UI) ou on remplace aussi ?
