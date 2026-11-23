# Journal : Tâche F : drapeau d'inscriptions (D11) et attribution à un grossiste (D9)

Branche : `task/f-partenaires-attribution` (worktree `C:\projets\hf-f`). Base : `69a5cbe` (`integration/v2`).

## 2026-11-22 : Point d'arrêt D11 (règle d), objectif 1 non codé

Lectures possibles de « `PARTNER_REGISTRATIONS_OPEN` ferme ou ouvre les inscriptions de partenaires » (EXECUTION_V2 § 3, D11) :

- **Lecture A** : le drapeau ferme les **nouvelles attributions de vendeuses** via le lien (création d'un `Referral`), et rien d'autre. Le clic compté, le cookie `hf_ref` et la bannière restent comme aujourd'hui. Lieu : `attribute_referral` (`partners/services/attribution.py`). Valeur par défaut : ouvert.
- **Lecture B** : le drapeau ferme l'**entrée dans le programme** (création de partenaires, acceptation des conditions ou des lettres d'essai en ligne). Lieu : hors `attribution.py` (`partners/services/acceptance.py`, `partners/admin_views.py`). Ne touche pas au lien.
- **Lecture C** (littérale : « appliquer dans `find_partner_for_new_referral` ») : **écartée**. `find_partner_for_new_referral` est aussi appelée par `referral_link_view` (`partners/views.py:33`, `:39`). Si elle renvoie `None` quand le drapeau est fermé, le clic n'est plus compté (`PartnerClick`, l. 35) et le cookie n'est plus posé. C'est contraire au principe du prompt (clics, cookie inchangés).

Pourquoi STOP : A et B changent des comportements différents, et la valeur par défaut se choisit avec la lecture. Ne pas deviner (règle d de la tâche). Objectif 1 (drapeau et tests) suspendu.

Objectif 2 (grossiste rattaché, D9) n'a pas besoin du drapeau : il est traité ci-dessous.

## 2026-11-22 : Décisions objectif 2

| Décision | Raison | Alternative écartée |
|---|---|---|
| `Referral.seller` passe nullable (`AlterField`, la contrainte `OneToOne` est conservée, elle autorise plusieurs NULL). Unicité grossiste = `UniqueConstraint` conditionnelle sur `distributor` (`condition=isnull=False`). | Une seule attribution par cible ; la vendeuse est déjà unique par `OneToOne`, inutile de dupliquer l'index. | Retirer le `unique` du `OneToOne` puis contrainte conditionnelle : écarté, changement de schéma sans gain. |
| `CheckConstraint` « exactement une cible » : `(seller NOT NULL, distributor NULL) OR (seller NULL, distributor NOT NULL)`. | D9 ; la règle est vérifiée par la base. | Contrôle seulement dans `clean()` : écarté, contournable. |
| `distributor` : `ForeignKey(distrib.Distributor, PROTECT, null=True, related_name="partner_referral")`. | PROTECT comme pour `partner` : une attribution ne disparaît pas avec le grossiste. | CASCADE : écarté. |
| Immuabilité de `Referral.save()` étendue à `distributor_id`. | Le Referral reste immuable pour la nouvelle cible (demande). | — |
| Requêtes de comptage et de relevé (`reporting.py`, `payouts.py`, `admin_views.py`) filtrées sur `seller__isnull=False`. | Un grossiste ne doit pas être compté comme vendeuse inscrite, ni dans les relevés ou les entonnoirs. | Ne rien filtrer : écarté (chiffres faux). |
| Migration `partners/0004_referral_grossiste` : schéma seulement, sans `RunPython`. | Règle b ; numéro 0004 libre dans tous les worktrees (0003 est le maximum partout). | — |
| Pas de commission sur Distrib, pas de statut « réglée » par ligne. | D9. | — |

Migration : `partners/0004`. Réversible au niveau schéma. Note : la réversion échoue si des lignes grossistes existent (la vendeuse redevient NOT NULL) : c'est voulu, elle doit être faite à la main.

## 2026-11-22 : Fin de tâche (état au commit `610605d`)

**Fait** (objectif 2, D9) :
- Schéma : `Referral.seller` nullable, `Referral.distributor` (FK PROTECT, `related_name="partner_referral"`), CHECK « exactement une cible », unique conditionnelle sur `distributor`, immuabilité étendue. Migration `partners/0004_referral_grossiste` (AddField, AlterField, 2 AddConstraint, aucun RunPython). Commit `3c2e250`.
- Compteurs et relevés filtrés sur `seller__isnull=False` (`reporting.py` : tableau de bord, entonnoir, dernière inscription, `_active_referrals` ; `payouts.py` : relevé ; `contract.py` ; `admin_views.py` : fiche partenaire). Un grossiste n'est jamais compté comme vendeuse.
- Service `partners/services/distributor_attribution.py` : `attribute_distributor()` (source, date, refus de doublon, `AuditLog` `partner.distributor_attributed`). Commit `9ef311c`. Aucun appel public.
- Admin grossistes : colonne « Apporté par », filtre (partenaire ou « Aucun partenaire »), saisie unique via le service, lecture seule ensuite. Commit `610605d`.
- Tests : `partners/tests_grossiste.py` (14), `partners/tests_grossiste_admin.py` (6), `partners/tests_migration_0004.py` (3, lignes vendeuses réelles au schéma 0003, forward, contraintes, réversion).

**Non fait** : objectif 1 (drapeau `PARTNER_REGISTRATIONS_OPEN`, D11). Point d'arrêt, voir la section du 22/11 ci-dessus. Aucun réglage ni test ajouté pour ce drapeau.

**Décisions complémentaires** :
- `Referral.seller` garde son `OneToOneField` (unicité déjà assurée, nulls distincts) ; seule la cible grossiste reçoit une contrainte unique conditionnelle. Évite un second index sur la même colonne.
- Aucune commission, aucun statut « réglée » (D9).
- Le service n'applique pas de condition d'éligibilité au partenaire (prospect, essai, contrat). Question ouverte.

**Validation** :
- `pytest --ds=config.settings.test partners` : 614 passed.
- `pytest distrib --ignore=distrib/tests_seed_demo.py` : 345 passed, 1 skipped.
- `makemigrations --check` : aucune migration manquante.
- `ruff` sur les fichiers nouveaux : propre. Les RUF012 présents dans `partners/models.py` et les migrations existaient avant la tâche : non traités.
- Non lancé : suite complète, tests de seed, `core/tests_deploy_nginx_recreate.py`.

**Questions ouvertes** :
1. D11 : lecture retenue ? A (ferme les nouvelles attributions de vendeuses seulement, clic et cookie intacts, défaut ouvert), B (ferme l'entrée dans le programme : création de partenaires, acceptation en ligne), ou C (filtre dans `find_partner_for_new_referral`, écartée : supprime le clic compté et le cookie).
2. Attribution d'un grossiste : faut-il exiger un partenaire actif sous contrat (comme `accepts_new_referrals`) ? Aujourd'hui le service accepte tout partenaire existant.
3. Un grossiste rattaché peut-il un jour être réattribué (cas d'erreur de saisie) ? Aujourd'hui non : correction par l'équipe en base, tracée à la main.

## 2026-11-22 : Reprise après décisions du fondateur

- **D11, lecture B, défaut fermé** : `PARTNER_REGISTRATIONS_OPEN` (base.py, défaut `false`, test.py ouvert pour les parcours existants). Ferme seulement l'acceptation en ligne de la lettre d'essai par un partenaire sans lettre (`self_service_closed_for`, `partners/services/acceptance.py`). Création admin, acceptation écrite, partenaires existants, liens, `hf_ref`, clics et attributions inchangés. Commits `08ff099`, `2703cc9`. Tests : `partners/tests_registrations_flag.py` (11 : fermé et ouvert, partenaire nouveau et existant, acceptation écrite, clic et cookie inchangés, défaut du réglage).
- **Attribution grossiste** : seul un partenaire au statut Actif avec acceptation non invalidée des conditions du programme peut amener un grossiste (`partner_can_bring_distributor`). Commit `1564986`. Tests : prospect et partenaire sans conditions refusés.
- **Attribution grossiste immuable** : inchangé. Correction future par action admin avec motif et AuditLog, hors périmètre.

**Validation finale (périmètre réduit demandé)** : `pytest --ds=config.settings.test partners` : 626 passed, 107 subtests passed. Une exécution élargie (distrib, accounts, core) a été lancée puis non attendue : aucun résultat retenu, non comptée comme validée.

**Non fait / reste** : distrib, accounts, core non revalidés dans cette reprise (la suite distrib précédente, hors seed, était verte : 345 passed, 1 skipped, avant le drapeau et la règle grossiste). Aucun test d'admin supplémentaire après la règle grossiste (les 6 tests admin passent avec la règle). Lint : `public_views.py` I001 pré-existant.

**Questions ouvertes** :
1. Le défaut fermé change le parcours de première acceptation en ligne pour tout nouveau partenaire dès déploiement (les partenaires existants ne changent pas). À confirmer avant mise en production.
2. Le gabarit affiche encore « Aucun document n'est à accepter » sous le message de fermeture. Acceptable, à trancher si on veut un texte unique.

## 2026-11-23 : Consigne de mise en service du drapeau

Avant d'intégrer le premier créateur (et sur l'environnement de test), définir `PARTNER_REGISTRATIONS_OPEN=True`.
Sans cette variable, la première acceptation en ligne d'un nouveau partenaire est refusée (défaut fermé, D11).
