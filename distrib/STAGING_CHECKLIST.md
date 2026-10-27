# Distrib — check-list de recette sur le staging (48 h)

Spec : `docs/specs/SPEC_03_DISTRIB_V1.md` §11 (scénario de base), §15.12 (compléments), §12 (mise en production). À cocher par le mainteneur ; **rien de ce document n'a été exécuté** (aucune action VPS ni déploiement faite par Claude).

## 0. Avant de commencer

- [ ] Staging uniquement (jamais la production) ; `DISTRIB_ENABLED=true` dans le `.env` du staging, web + worker + **beat** redémarrés (le planning `distrib.*` n'est chargé que si l'interrupteur est actif).
- [ ] Sauvegarde base + médias du staging faite ; tag git `v-avant-distrib` posé.
- [ ] Migrations `distrib` appliquées (`manage.py migrate`), `makemigrations --check` propre.
- [ ] 1 grossiste de test créé au pilotage (`/distrib/pilotage/`), mot de passe provisoire noté une seule fois.
- [ ] 2 revendeurs de test (boutiques réelles) + 1 **second grossiste** de test (pour le cloisonnement).
- [ ] Vrais téléphones : grossiste, 2 revendeurs, 2 clientes (dont une qui commande depuis un **autre** téléphone que celui du bandeau).
- [ ] Pour tester la confirmation automatique : régler `auto_confirm_hours` à **1 h** sur le grossiste de test (admin Django). Le remettre à 72 ensuite.
- [ ] Staging non indexable (`robots.txt`), aucun SMS (`SMS_NOTIFICATIONS_ENABLED` faux).

## 1. Scénario de base (§11)

- [ ] Invitation du revendeur A par le grossiste → bandeau visible sur `/seller/` du bon numéro **seulement**.
- [ ] Acceptation → « Mes grossistes » affiche le grossiste ; le refus du revendeur B ne rattache rien.
- [ ] Catalogue : 1 produit avec photo, prix de gros, prix minimum, stock 10.
- [ ] Allocation de 5 unités à A ; import par A (prix ≥ minimum ; un prix sous le minimum est refusé).
- [ ] Vente flash de A avec ce produit ; 3 commandes :
  - [ ] commande 1 : livrée, puis « Livré et payé » → `paid_confirmed` ;
  - [ ] commande 2 : annulée par la vendeuse → ligne `cancelled`, stock rendu ;
  - [ ] commande 3 : payée d'avance (confirmée avant livraison).
- [ ] Statuts **identiques** chez le grossiste, le revendeur (Mes gains) et en pilotage ; stock total / alloué / vendu / disponible correct.
- [ ] Marge, commission et encours exacts (commission « offerte » pendant l'essai ; encours = 0 tant que non facturable).
- [ ] Reprise de stock (uniquement le non vendu) ; allocation au-delà du disponible refusée.
- [ ] Cloisonnement avec le 2e grossiste : il ne voit ni revendeurs, ni commandes, ni produits du premier ; il ne voit pas les produits **non importés** de la boutique.

## 2. Compléments (§15.12)

- [ ] **Confirmation automatique** : une commande laissée sans action ; compte à rebours visible (grossiste, revendeur) ; après 1 h → `paid_confirmed` source « Automatique » (jamais avant l'échéance) ; une commande restée `pending` n'est jamais auto-confirmée.
- [ ] **« Pas livré »** : motif choisi dans la liste (le champ de précision n'apparaît que pour « Autre ») ; la commande de la boutique et le stock sont **inchangés** ; réaffectation volontaire via l'allocation ; impossible après `paid_confirmed`.
- [ ] **Confirmation cliente par le bandeau** (même téléphone que la commande) : bandeau discret, « J'ai reçu » ; référence Orange Money facultative visible des trois parties.
- [ ] **Confirmation cliente par la page de secours** (autre téléphone) : `/distrib/confirmer/` avec numéro + code à 4 chiffres ; un mauvais code donne une réponse neutre ; le code n'apparaît **jamais** côté grossiste/revendeur.
- [ ] **Confirmation cliente sur une ligne « Pas livré »** : aucun changement de statut ; signal `conflict` visible **au pilotage seulement**.
- [ ] **Relevé hebdomadaire** : clôture du lundi (ou lancement manuel de la tâche) → un relevé par revendeur, montant = somme des marges, aucun champ montant ; « Payé » + référence OM ; double clic sans effet.
- [ ] **Versement contesté** : « Pas reçu » (motif de liste) → versement et relevé contestés, montant toujours dû, signal au pilotage ; redéclaration unique du grossiste avec une autre référence ; 2e contestation → relevé escaladé, grossiste sans action, clôture/réouverture par le staff, journalisées.
- [ ] **Silence = accord** : un versement non contesté devient « Accepté » après 72 h (à vérifier en avançant `contest_deadline` en admin).
- [ ] **Plafond de marges** : dépasser le plafond d'un revendeur → nouvelles allocations/importations bloquées (message clair), commandes en cours et ventes ouvertes **non** bloquées ; régler le relevé → déblocage automatique. Alerte orange dès 80 %.
- [ ] **Plafond de commission** (encours) : même vérification pour le grossiste entier.

## 3. Écrans P8 (mobile d'abord)

- [ ] Sur téléphone : accueil, commandes, revendeurs, Mes grossistes, Mes gains, pilotage tiennent sans défilement horizontal ; boutons larges et lisibles.
- [ ] Les écrans se mettent à jour d'eux-mêmes en ≤ 30 s (passer une commande pendant que l'accueil est ouvert).
- [ ] Ouvrir « Pas livré » ou « Pas reçu » et attendre 30 s : le formulaire **reste ouvert** et la saisie n'est pas perdue.
- [ ] Le compte à rebours décroît entre deux rafraîchissements.
- [ ] Pilotage : l'indice de fiabilité (taux de « Pas livré », conflits, versements contestés, retards, répartition des confirmations) est cohérent avec le scénario ; **absent** des écrans grossiste et revendeur.
- [ ] Console navigateur sans erreur CSP (la CSP est en Report-Only : surveiller `report-uri` / Sentry).

## 4. Non-régression

- [ ] Commande normale (produit **non** importé) : inchangée, aucun suivi créé.
- [ ] Commande sur produit importé avec Celery arrêté : la commande aboutit ; au redémarrage, la réconciliation (≤ 5 min) crée la ligne.
- [ ] Publication rapide, dashboard LIVE, paiements d'abonnement : inchangés.
- [ ] Retour arrière à blanc : `DISTRIB_ENABLED=false` → `/distrib/` en 404, plus de bandeau ni de lien « Confirmer un paiement », les produits importés se vendent normalement ; puis réactivation.

## 5. Conditions bloquantes avant la production (§12, §15.13)

- [ ] CGU mises à jour : transmission de l'adresse de livraison au grossiste qui livre ; collecte facultative de la référence Orange Money (visible boutique, grossiste livreur, HayaFlash).
- [ ] Contrat grossiste signé : présomption de livraison 72 h, obligation de motif et d'exactitude des « Pas livré » (suspension possible en cas d'écarts répétés), versement hebdomadaire avec référence OM, silence 72 h = acceptation, plafond de marges dues, commission 5–6 % plafonnée à 1 500 FCFA/commande offerte pendant l'essai, plafond d'encours, prix minimum, refus de livraison.
- [ ] Production : moment sans vente flash en cours → sauvegarde base + médias + tag `v-avant-distrib` → déploiement avec `DISTRIB_ENABLED=false` + tests rapides → activation → premier grossiste (pilote 2 mois, commission 0).

## 6. Couverture automatisée (revue P10)

| Spec | Tests (`distrib/`) |
|---|---|
| §10-1 interrupteur | `tests_settlement.SwitchAndFailureTests::test1_*`, `tests_models.FeatureSwitchTests`, `*::off_means_404` |
| §10-2, 3 | `tests_settlement.CreationAndMoneyTests::test2_*`, `SwitchAndFailureTests::test3_*` |
| §10-4, 5, 6 | `StatusSyncTests::test4_*`, `PresumptionTests`/`EarlyConfirmationTests::test5_*`, `OrdersPageTests::test6_*`, `tests_allocation.*::cloisonnement_*` |
| §10-7 invitations | `tests_invites.*` |
| §10-8, 9 | `tests_allocation.AllocateTests`, `TakeBackTests`, `ImportTests::price_below_minimum_*` |
| §10-10, 11 | `tests_money.CommissionTests`, `WeeklyStatementTests::margin_due_*`, `tests_allocation.CeilingTests` |
| §10-12 suite existante + lint | suite complète et `ruff check . --select E,F,W --ignore E501` |
| §15.11-13 | `tests_settlement.PresumptionTests` |
| §15.11-14 | `tests_settlement.NotDeliveredTests` |
| §15.11-15 | `tests_settlement.CancelAfterConfirmationTests` (a à d), `EarlyConfirmationTests` |
| §15.11-16, 17 | `tests_receipts.*` (`test17_*`) |
| §15.11-18 | `tests_money.PayoutLifecycleTests` |
| §15.11-19 | `tests_allocation.CeilingTests`, `tests_money::test19_*` |
| §15.11-20 | `tests_money.CommissionTests` |
| §15.11-21 fiabilité | `tests_reliability.ReliabilityIndexTests::test_test21_*` (+ seuils, fenêtre, cloisonnement) |
| §15.11-22, 23 | `tests_money.WeeklyStatementTests`, `PayTests` |
| §15.11-24, 25 | `tests_money.ReversalAndAlertTests` (`test24_*`, `test25_*`) |
| P8 écrans, §15.8 | `tests_reliability.DashboardPagesTests`, `NoFreeTextTests`, `NoInlineScriptTests` |

Limites connues à garder en tête pendant la recette : plusieurs clientes derrière une même IP mobile partagent le quota de 5 essais/heure de `/distrib/confirmer/` (CGNAT) ; `conflict_flag` n'a pas d'horodatage propre (l'indice de fiabilité utilise `updated_at`) ; le suivi est par article importé (l'UI cliente ne commande qu'un produit à la fois).
