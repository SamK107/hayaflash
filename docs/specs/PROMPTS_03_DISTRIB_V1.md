# Prompts Claude Code — Distrib V1

Référence unique : `docs/specs/SPEC_03_DISTRIB_V1.md` (§1–14 + **Avenant A §15, prioritaire**).
`docs/evolutions/SPEC_DISTRIB.md` est obsolète : ne pas l'utiliser.

Mode d'emploi : **une session Claude Code par prompt**, dans l'ordre. Ne lancer le suivant qu'après
avoir lu le rapport de fin du précédent. Tout se fait sur la branche `feature/distrib`.

---

## PROMPT 1 — P0 : constats (aucun code applicatif)

```
Tu travailles sur HayaFlash (Django, en production avec de vrais clients).
Lis CLAUDE.md, docs/ROADMAP_V2_V3.md §0 et docs/specs/SPEC_03_DISTRIB_V1.md EN ENTIER
(l'Avenant A §15 prévaut sur le reste). Ignore docs/evolutions/SPEC_DISTRIB.md (obsolète).

Règles : aucun push, merge, déploiement ni action VPS. Aucun fichier hors périmètre §8.

1. Crée la branche feature/distrib depuis main à jour. Lance la suite de tests complète et le lint :
   consigne le résultat (doit être vert avant de continuer).
2. Phase P0 uniquement : réponds par écrit, avec chemins et numéros de ligne, à :
   a. Order/OrderItem : une commande peut-elle avoir plusieurs articles ? (§3)
   b. Services products/ utilisables pour créer un Product, ajuster le stock ; verrouillage
      select_for_update présent ? (§5.3)
   c. Circuit d'annulation utilisé par la vendeuse : quelle fonction/vue, appelable depuis
      une autre app SANS modification, libère-t-elle le stock via release_order_stock ? (§15.2)
   d. templates/orders/client_order.html : un seul {% include %} conditionnel est-il possible
      pour le lien discret + code 4 chiffres ? Comment connaître la commande créée à cet endroit ? (§15.3)
   e. Gabarit commun des pages publiques : où placer un seul {% include %} pour le lien
      « Confirmer un paiement » et le bandeau ? (§15.3)
   f. Redirection après connexion pour un utilisateur sans SellerProfile (§5.1).
   g. Template du tableau de bord vendeur pour le bandeau d'invitation (§5.2).
3. Écris ces constats dans distrib/README.md (crée seulement ce fichier) et commit
   « docs(distrib): constats P0 ».
4. ARRÊTE-TOI. Rapport final : constats, points bloquants, écarts avec la spec, recommandations.
   Si un point de §15.2 ou §15.3 n'est pas faisable proprement, dis-le et propose le repli prévu.
   Ne code rien d'autre.
```

---

## PROMPT 2 — P1 à P5 : fondations, comptes, invitations, catalogue, allocation

```
Reprends HayaFlash, branche feature/distrib. Lis distrib/README.md (constats P0) et
docs/specs/SPEC_03_DISTRIB_V1.md (Avenant A §15 prioritaire). Respecte strictement §2 et §8.

Implémente les phases P1 à P5, un commit par phase, tests écrits au fil de l'eau :
- P1 : app distrib, TOUS les modèles §4 + ajouts §15.9 (migrations additives dans distrib
  uniquement), admin Django, interrupteur DISTRIB_ENABLED=False par défaut (§7), .env.example.
- P2 : création de grossiste au pilotage, /distrib/connexion/.
- P3 : invitations, bandeau (un seul include), page de consentement.
- P4 : catalogue de gros + images.
- P5 : import, allocation, reprise (distrib/services/allocation.py), en APPELANT les services
  products existants sans les modifier ; blocage léger si plafond dépassé (§15.6, la règle de
  blocage peut être un stub testé, le calcul complet vient en P7).

Contraintes : montants FCFA entiers ; numéros E.164 via core/countries.py ; textes français en dur
(pas de gettext) ; mobile d'abord. Aucun fichier interdit par §8 modifié : vérifie avec
`git diff --stat main` avant chaque commit.

À la fin : suite complète + lint verts. ARRÊTE-TOI et rapporte : commits, fichiers touchés
(git diff --stat main), tests ajoutés, écarts éventuels avec la spec. Pas de push.
```

---

## PROMPT 3 — P6, P6b, P7 : suivi, confiance et contrôle, argent

```
Reprends HayaFlash, branche feature/distrib. Relis distrib/README.md et SPEC_03 §5.4–5.6 et
§15 en entier : c'est le cœur du module, l'Avenant A prévaut.

Implémente, un commit par phase :
- P6 : signal post_save Order + transaction.on_commit + try/except/log ; réconciliation beat 5 min ;
  correspondance des statuts ; présomption de livraison à auto_confirm_hours (tâche beat 15 min,
  idempotente, select_for_update) ; « Livré et payé » anticipé par le grossiste ; « Pas livré » avec
  motif, qui APPELLE le circuit d'annulation identifié en P0 (jamais d'écriture directe de
  Order.status, aucune modification de orders/) ; statut not_delivered jamais écrasé ;
  aucune rétrogradation de paid_confirmed ; DistribCorrection (staff uniquement).
- P6b : confirmation cliente §15.3 — receipt_token, receipt_code 4 chiffres (jamais exposé côté
  revendeur/grossiste), cookie hf_receipts, bandeau discret, page /distrib/confirmer/ (numéro +
  code), limites de débit, réponse neutre, référence OM facultative, conflict_flag. Les deux
  includes exactement comme validés en P0 ; sinon le repli prévu.
- P7 : commission §15.7 (calculée dès le mois 1, commission_billable après pilot_until, plafond
  1 500 FCFA/commande) ; encours ; versements ResellerPayout declared/accepted/contested avec
  acceptation auto à 72 h ; deux plafonds §15.6 (alerte 80 %, blocage des nouvelles allocations
  et importations au-delà, jamais des commandes en cours, déblocage auto).

Écris les tests §10 et §15.11 correspondants (13 à 20). Les tests 2 et 3 (une commande aboutit
toujours, même si le signal plante) sont obligatoires et doivent passer.

À la fin : suite complète + lint verts ; git diff --stat main sans fichier interdit.
ARRÊTE-TOI et rapporte, avec la liste des tests §15.11 couverts. Pas de push.
```

---

## PROMPT 4 — P8 et P10 : écrans, fiabilité, finitions

```
Reprends HayaFlash, branche feature/distrib. Relis SPEC_03 §6, §15.5, §15.8 et §15.12.

- P8 : tableaux de bord grossiste (/distrib/), revendeur (« Mes grossistes », « Mes gains »,
  « Pas reçu »), pilotage (/distrib/pilotage/, staff) ; HTMX 30 s ; compte à rebours de
  confirmation auto ; gros boutons, sans saisie libre hors motif « other » ; indice de fiabilité
  §15.5 au pilotage uniquement. Design soigné, mobile d'abord, cohérent avec l'existant.
- P9 : NE PAS faire (facultative, touche core/analytics).
- P10 : test 21 (fiabilité) et revue de toute la couverture §10 + §15.11 ; lint ; section Distrib
  dans CLAUDE.md ; distrib/README.md complété (fonctionnement, réglages, retour arrière §13) ;
  check-list du scénario staging §11 + §15.12 dans distrib/STAGING_CHECKLIST.md.

À la fin : suite complète + lint verts ; git diff --stat main ; rapport final avec ce qui reste
pour le staging. Pas de push, pas de merge, pas de déploiement : j'en décide après relecture.
```
