# Runbook — test de paiement réel (100 FCFA) et changement de tarif

> Créé le 26/09/2026 avec les tarifs administrables (`PlanConfig`) et les tarifs
> spéciaux par vendeur (`SellerPriceOverride`). Remplace l'ancien « mode test
> par variable `.env` » (abandonné) : le montant de test est un **tarif spécial
> attribué à un seul compte vendeur de test**, jamais un réglage global.
>
> Tout se fait depuis l'admin Django (`/admin/`), sans redéploiement.

---

## 1. Test de paiement réel à 100 FCFA

On le déroule d'abord **en local** (tunnel ngrok), puis **en prod** avec le même
compte de test. On ne touche jamais au prix des autres vendeurs.

### 1.0 Préparation (local uniquement)

Orange Money doit joindre une URL HTTPS publique : ni `localhost` ni l'IP du
PC.

```powershell
ngrok http 8000
```

Dans `.env`, avec l'URL affichée par ngrok (elle change à chaque lancement de
ngrok) :

```
ORANGE_ML_BASE_URL=https://xxxx.ngrok-free.app
ORANGE_ML_RETURN_URL=https://xxxx.ngrok-free.app/billing/return/
ORANGE_ML_CANCEL_URL=https://xxxx.ngrok-free.app/billing/cancel/
ORANGE_ML_NOTIFY_URL=https://xxxx.ngrok-free.app/billing/webhook/orange/
```

⚠️ **Les trois URLs explicites sont nécessaires.** Avec seulement
`ORANGE_ML_BASE_URL`, Orange est renvoyé vers l'ancien webhook
`/seller/abonnement/callback/`, qui active bien l'abonnement mais **n'écrit pas
de `WebhookLog`**, donc l'étape 4 ne serait pas vérifiable. La variable
s'appelle `ORANGE_ML_BASE_URL` dans `.env` (le setting Django correspondant
est `ORANGE_MONEY_BASE_URL`).

Redémarrer le serveur, puis vérifier la configuration sur
`/seller/abonnement/debug-om/` (DEBUG uniquement) : `token_ok: true`,
`BASE_URL_ok: true`.

En prod : les mêmes variables, avec le vrai domaine.

### 1.1 Compte vendeur de test

Un compte **dédié** (ex. boutique « Test paiement HayaFlash »), sans
abonnement payant actif. Un tarif spécial est **refusé** pour un vendeur qui a
déjà un plan payant actif : c'est voulu, un test ne doit jamais prolonger un
vrai abonnement.

### 1.2 Créer le tarif spécial

`/admin/` → **Tarifs spéciaux vendeurs** → Ajouter :

| Champ | Valeur |
|---|---|
| Vendeur | le compte de test (recherche par nom, code ou téléphone) |
| Plan | Medium |
| Prix spécial | `100` |
| Durée (jours) | `1` |
| Motif | Test de paiement (+ précision : « test réel Orange JJ/MM ») |
| Début | maintenant |
| Fin | maintenant + 2 h |
| Utilisations max | `1` |

Attendu : dans la liste, statut **Actif**, utilisations `0/1`. Une entrée
`price_override.created` apparaît dans le journal d'audit.

### 1.3 Payer

Se connecter avec le compte de test → **Mon abonnement** → Choisir Medium.
La page de paiement affiche :

> **Tarif spécial : 100 FCFA** au lieu de 2 000 FCFA, valable jusqu'au … —
> abonnement de 1 jour.

Le vendeur ne peut rien saisir : le montant est recalculé côté serveur.
Saisir le numéro Orange Money, puis **Payer 100 FCFA**.

✅ **Sur la page Orange Money, vérifier que le montant affiché est bien
100 FCFA** (et non 2 000, ni 10 000 : aucune conversion ×100 n'existe). S'il
diffère, **ne pas payer** : annuler, puis relever le montant et l'`order_id`.

### 1.4 Vérifier (admin + shell)

Après le paiement, et une fois la page « Paiement en attente » passée en succès :

| Où | Attendu |
|---|---|
| Admin → Paiements abonnement | le paiement : montant `100`, **Tarif spécial ✔**, statut **Succès**, `paid_at` renseigné, `price_override` = le tarif créé |
| Admin → Logs webhooks Orange Money | une ligne pour ce `notif_token`, `processed` ✔, statut `SUCCESS` |
| Admin → Abonnements | vendeur de test en **Medium**, `expires_at` ≈ maintenant + 1 jour |
| Admin → Tarifs spéciaux | statut **Épuisé**, utilisations `1/1` |
| `/platform-admin/` | « Tests (hors CA) : 100 FCFA (1) » ; MRR, total et CA annuel **inchangés** ; la rétrocession Orange inclut les 100 FCFA (argent réellement encaissé) |
| Page Mon abonnement (compte de test) | un nouveau paiement proposerait le prix officiel (tarif épuisé) |

Vérification en shell si besoin :

```powershell
python manage.py shell --settings=config.settings.dev -c "from subscriptions.models import SubscriptionPayment as P; p=P.objects.filter(is_special_price=True).latest('created_at'); print(p.amount, p.status, p.price_override_id, p.webhook_logs.count())"
```

### 1.5 Dérouler aussi l'annulation et l'échec

Pour chaque cas, créer un **nouveau** tarif spécial (le précédent est épuisé),
ou remettre temporairement `max_uses` à 2.

- **Annulation** : sur la page Orange, « Annuler ». Attendu : retour sur Mon
  abonnement avec « Paiement annulé », paiement **Annulé**, abonnement
  inchangé, tarif **non consommé** (`0/1`).
- **Échec** : paiement refusé (solde insuffisant ou code faux). Attendu : webhook
  `FAILED` → paiement **Échec**, `WebhookLog` écrit, abonnement inchangé, tarif
  **non consommé**.

### 1.6 Fin du test

Vérifier que le tarif est **Épuisé** ou le passer en **Désactiver maintenant**
(action de liste). Il ne peut plus servir. Le paiement garde son historique :
un tarif déjà utilisé ne peut pas être supprimé (PROTECT).

---

## 2. Changer un tarif officiel

**Où** : `/admin/` → **Configuration des plans** → Medium ou Pro. Il y a
3 lignes fixes, sans ajout ni suppression possible.

**Champs** : prix (FCFA entiers, 100 minimum pour un plan payant, 0 pour
Gratuit), ventes par mois (vide = illimité ; Medium ≤ Pro), durée en jours,
fonctionnalités (liste JSON ; la ligne du quota est ajoutée automatiquement),
actif (un plan payant inactif n'est plus proposé).

**Effet** :

- **Nouveaux paiements uniquement.** Un paiement garde son montant
  (`SubscriptionPayment.amount`), un abonnement en cours garde son échéance.
- Le quota et les textes (pages Abonnement, modale d'upgrade, paramètres,
  statistiques) suivent immédiatement en prod (cache Redis partagé,
  invalidé à l'enregistrement). En local, chaque processus a son propre
  cache : jusqu'à **60 s** de délai.
- Chaque modification est tracée dans le journal d'audit
  (`plan_config.updated`, valeurs avant/après, auteur).
- Un tarif spécial existant reste valable tant qu'il est ≤ au nouveau prix
  officiel ; au-delà, c'est le prix officiel qui s'applique.

**Vérification** : se connecter avec un compte vendeur **sans tarif spécial**
→ **Mon abonnement** : la carte du plan affiche le nouveau prix, et la page de
paiement le même montant (« Payer N FCFA »). Contrôler aussi la modale
« Choisissez votre plan » (page Mes ventes).

**Retour arrière** : remettre l'ancienne valeur (le journal d'audit la donne).
