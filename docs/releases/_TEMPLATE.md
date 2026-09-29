# Suivi de release — vX.Y.Z-rcN

> Copier ce fichier en `docs/releases/<version>.md`. Règles, phases et
> commandes : `GOVERNANCE_RELEASE.md`. Statuts : ⬜ à faire · 🔄 en cours ·
> ✅ fait et prouvé · ❌ non conforme. Pas de ✅ sans preuve (fichier:ligne,
> test, PR, rapport dans `docs/releases/reports/`). L'audit coche.

| Champ | Valeur |
|---|---|
| Version | vX.Y.Z-rcN |
| Base `main` au démarrage | `<SHA>` |
| Branche du suivi | `<branche>` |
| Ouvert le | AAAA-MM-JJ |
| Tag rc posé | ⬜ `<SHA>` le AAAA-MM-JJ |
| Décision Go / No-Go | ⬜ |

---

## Phase 0 — Gel & hygiène du dépôt

| ID | Item | Statut | Preuve |
|---|---|---|---|
| P0-1 | Gel des features déclaré (seuls les correctifs d'audit entrent, via PR) | ⬜ | |
| P0-2 | Règle des branches (GOVERNANCE_RELEASE.md §3) : chaque branche a un critère (a), (b) ou (c) | ⬜ | |
| P0-3 | gitleaks sur tout l'historique : 0 fuite — **bloquant avant le tag** (GOVERNANCE_RELEASE.md §3 bis) | ⬜ | |
| P0-4 | Tous les findings bloquants ✅ (PR en preuve) | ⬜ | |
| P0-5 | Tag posé | ⬜ | |

Branches non fusionnées au moment du tag :

| Branche | Critère (a) PR / (b) DEJA INTEGREE / (c) abandonnée | Preuve |
|---|---|---|
| | | |

## Phase 1 — Matrice de traçabilité des gouvernances

### Inventaire des documents de gouvernance

| Document | Référencé par | Exigences extraites | IDs | Remarque |
|---|---|---|---|---|
| | | | | |

### Règles métier (prioritaires), puis une section par document

| ID | Exigence (source fichier:ligne) | Implémentation (fichier:ligne) | Test couvrant | Statut | Preuve | Finding |
|---|---|---|---|---|---|---|
| | | | | ⬜ | | |

## Phase 2 — Backend, données & tests

| ID | Item | Statut | Preuve |
|---|---|---|---|
| P2-1 | pytest `--ds=config.settings.test_pg`, 0 skipped | ⬜ | |
| P2-2 | Couverture ≥ 90 % (subscriptions, orders, payments, callback Orange) | ⬜ | |
| P2-3 | `makemigrations --check --dry-run` | ⬜ | |
| P2-4 | `migrate` depuis une base vide, PostgreSQL 16 | ⬜ | |
| P2-5 | `check --deploy` (settings prod, valeurs factices) | ⬜ | |
| P2-6 | Celery worker + beat réels (auto-close) | ⬜ | |

## Phase 3 — Sécurité

| ID | Item | Statut | Preuve |
|---|---|---|---|
| | | ⬜ | |

## Phase 4 — Staging isolé sur le VPS & cohabitation avec services.symain.africa

| ID | Item | Statut | Preuve |
|---|---|---|---|
| | | ⬜ | |

## Phase 5 — Tests fonctionnels sur staging

| ID | Item | Statut | Preuve |
|---|---|---|---|
| | | ⬜ | |

## Phase 6 — Paiement réel

| ID | Item | Statut | Preuve |
|---|---|---|---|
| | | ⬜ | |

## Phase 7 — Go / No-Go puis production

| ID | Item | Statut | Preuve |
|---|---|---|---|
| | | ⬜ | |

---

## Registre des findings

| ID | Constat | Référence | Phase | Bloquant | Statut | Correction (PR) | Preuve |
|---|---|---|---|---|---|---|---|
| F-01 | | | | oui / non / à qualifier | ⬜ | | |

## Questions ouvertes

| ID | Question | Pour | Réponse |
|---|---|---|---|
| Q1 | | | |

## Rapports

| Date | Rapport | Résultat |
|---|---|---|
| | `docs/releases/reports/…` | |
