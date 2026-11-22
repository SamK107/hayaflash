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
