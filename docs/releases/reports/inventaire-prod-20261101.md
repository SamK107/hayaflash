# Inventaire de la production avant le premier grossiste réel — 01/11/2026

Relevé en **lecture seule** par le mainteneur sur le VPS (`/srv/hayaflash-prod`), le 01/11/2026 vers 14 h 25 (heure du serveur).
Outil : `scripts/inventory_before_first_wholesaler.py` (aucune écriture, téléphones masqués).
Aucune donnée personnelle (noms, numéros) n'est reprise ici : les comptes sont désignés par leur code.

## Résultat

| Domaine | Constat |
|---|---|
| Distrib | **Vide** : 0 grossiste, 0 invitation de revendeur, 0 produit importé, 0 règlement. La purge du 31/10 (`purge_test_data.py`) est confirmée. |
| Vendeurs | 2 boutiques. `SLR-7AC8EHRA` : plan `medium`, 1 paiement d'abonnement réussi à tarif spécial, aucun produit ni vente. `SLR-HAP3B5QQ` : **vendeur pilote réel** (confirmé par le mainteneur), 1 vente clôturée, 1 produit. |
| Produit du vendeur pilote | Produit #4 avec `stock = 0/0` (stock disponible / stock initial) : en l'état il ne peut pas être vendu. À qualifier avec le vendeur. |
| Commandes et paiements | **0 commande**, 0 livraison, 0 `PaymentTransaction`, 0 `LedgerEntry` ; 1 paiement d'abonnement (`success`, tarif spécial) ; 20 lignes d'`AuditLog`. Aucune vente pilote n'a encore généré de commande réelle en production. |
| Comptes sans boutique | 2 comptes `staff` + `superuser` portant le même nom d'affichage et le même numéro masqué. **À qualifier** (compte de secours voulu ou doublon). Aucune modification faite. |

## Sauvegardes (journal `/home/sam/sauvegardes/prod/backup.log`)

Cinq dernières lignes relevées : exécutions quotidiennes à 02 h 45, toutes `OK`, du 28/10 au 01/11/2026.
Base : 224 Ko puis 280 Ko (depuis le 31/10). Médias : 980 Ko jusqu'au 31/10, **4,4 Mo le 01/11**.

Observation non élucidée : les médias passent de 980 Ko à 4,4 Mo entre les sauvegardes du 31/10 et du 01/11, alors que la base ne contient plus que le produit #4. Hypothèse (non vérifiée) : fichiers médias de la session de test du 31/10 restés sur disque après la purge de la base. À vérifier en lecture seule avant d'inviter le grossiste.

Non vu : la première sauvegarde (23/10) ; la copie hebdomadaire vers `D:\sauvegardes-vps\prod` n'a pas été contrôlée ici.

## Configuration relevée dans le `.env` de production

- `DISTRIB_ENABLED=True` (intentionnel, voir F-164).
- `SMS_NOTIFICATIONS_ENABLED` **absent** : valeur par défaut fausse (`config/settings/base.py:615`), donc aucun SMS.
- `ORANGE_ML_CLIENT_ID`, `ORANGE_ML_CLIENT_SECRET`, `ORANGE_ML_MERCHANT_KEY`, `ORANGE_ML_BASE_URL` (`https://hayaflash.com`), `ORANGE_ML_CURRENCY` : renseignées (seule la présence a été relevée, jamais les valeurs). **Clés réelles, confirmé par le mainteneur le 02/11/2026** (Orange fournit les mêmes identifiants en bac à sable et en production ; voir F-165).

## Complément du 02/11/2026 — doublon de compte staff supprimé

Le rapport en lecture seule (script ponctuel hors dépôt, rapport puis `APPLY=1`) a confirmé deux comptes `haya`, staff + superuser, sans boutique, créés à 6 minutes d'intervalle le 19/10/2026 :

| | Compte #1 | Compte #2 |
|---|---|---|
| Créé le | 19/10 14:56 | 19/10 15:02 |
| Dernière connexion | 19/10 15:28 | jamais |
| Données rattachées | 1 entrée du journal admin, 4 `AuditLog` (SET_NULL) | aucune |

Le #2 (le plus récent, jamais utilisé, sans aucune donnée rattachée, 0 objet en cascade ou protégé) a été **supprimé** par le mainteneur le 02/11/2026 ; le #1 est conservé. **Preuve de connexion** : le mainteneur s'est connecté à `https://hayaflash.com/admin/` avec le compte conservé (téléphone et mot de passe) le 02/11/2026, après la suppression.
