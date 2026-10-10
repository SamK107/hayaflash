# Programme partenaires : règles, formules, exemples

> Référence des règles implémentées dans l'app `partners` (branche `feat/programme-partenaires`,
> travail non commité). Les constantes viennent de `config/settings/base.py` (et `test.py`) ; les changer
> ne touche que les NOUVEAUX partenaires (pourcentage) ou les calculs futurs.

## Vocabulaire

Partout dans l'interface, les documents, le relevé, le CSV partenaire et les messages types : « vendeur
inscrit via le lien » (ou « via votre lien »), « lien personnel », « code ». Les mots « parrain »,
« parrainage », « filleul » et « recommand* » sont interdits dans ce périmètre (test
`partners/tests_documents.py::VocabularyTests`, limité à `templates/partners/`, aux documents, au relevé, au
CSV partenaire, aux messages types et aux libellés des modèles ; « Recommandé » reste autorisé ailleurs, il
désigne le plan Pro). Les identifiants du code (`Referral`, `referral_id`) ne changent pas.

## Constantes

| Constante | Valeur | Rôle |
|---|---|---|
| `PARTNER_COMMISSION_PERCENT` | 30 | Pourcentage par défaut, **figé à la création du partenaire** |
| `ORANGE_RETENTION_PERCENT` | 1 | Retenue Orange avant calcul de la commission |
| `PARTNER_COMMISSION_MONTHS` | 12 | Durée des commissions par vendeur inscrit via le lien, depuis son premier paiement |
| `PARTNER_CONTRACT_MONTHS` | 12 | Durée du contrat (1 an, non renouvelable) |
| `PARTNER_TRIAL_DAYS` | 30 | Durée de l'essai et de l'accès Pro offert |
| `PARTNER_FOUNDER_SLOTS` | 20 | Places de fondateur (sous contrat, actives ou en pause) |
| `PARTNER_MIN_PAYOUT_FCFA` | 2 000 | Minimum de versement, cumulable d'un mois à l'autre |
| `PARTNER_PAYOUT_DEADLINE_DAY` | 10 | Versement avant le 10 du mois suivant |
| `PARTNER_REFERRAL_COOKIE_DAYS` | 30 | Durée du cookie `hf_ref` |
| `PARTNER_ACCEPT_LINK_DAYS` | 30 | Validité d'un lien d'acceptation envoyé par WhatsApp |
| `PARTNER_INACTIVE_ALERT_DAYS` | 60 | Alerte « partenaire inactif » |
| `RATELIMIT_REFERRAL_IP` / `RATELIMIT_PARTNER_LINK_IP` | 60 / 30 par minute | Limites par IP : `/r/<code>/` et pages par lien privé |
| `LEGAL_ENTITY_*`, `LEGAL_JURISDICTION` | vide (sauf le nom) | Identité de l'éditeur dans les documents (environnement) |

## Statuts et phases d'un partenaire

| Statut | Sens |
|---|---|
| Prospect | Contacté, n'a rien accepté. Ne compte ni dans les places ni dans l'attribution. |
| Actif, en pause, terminé, place libérée | Comme avant. |

| Phase | Sens |
|---|---|
| Aucune | Pas encore d'essai. |
| Essai | Lettre d'essai acceptée ; 30 jours ; reçoit des inscriptions via son lien jusqu'à la fin de l'essai ; **ne prend pas de place** ; ne gagne aucune commission. |
| Contrat | Conditions du programme acceptées ; contrat d'un an ; occupe une place de fondateur. |
| Terminée | Fin d'essai sans contrat (aucune commission) ou fin de contrat (droits acquis conservés). |

Un partenaire créé dans le Django admin est « sous contrat » par défaut (compatibilité avec les blocs
précédents) ; il ne gagne pourtant aucune commission tant qu'aucune acceptation des conditions n'existe.

## Documents versionnés et acceptation en ligne

- Documents : **lettre d'essai v1.0** et **conditions du programme v1.0** (à accepter), **brief v1.0**
  (informatif, statut brouillon, rien à accepter). Gabarits figés : `templates/partners/legal/*_v1_0.html`.
- **Verrou de version** : `partners/tests_documents.py::VersionLockTests` compare le SHA-256 du texte
  canonique de chaque version publiée à une constante. Modifier un texte publié fait échouer le test : il
  faut créer une nouvelle version (`v1_1`, nouvelle constante de version), jamais éditer l'ancienne. Les
  acceptations déjà faites gardent leur texte exact (`text_snapshot`).
- **Identité de l'éditeur** : variables d'environnement `LEGAL_ENTITY_NAME` (défaut : ABEXPERTISES, entreprise individuelle),
  `_FORM`, `_CAPITAL`, `_ADDRESS`, `_RCCM`, `_CONTACT` et `LEGAL_JURISDICTION` (vides par défaut, jamais
  inventées). Un document est « complet » si les 6 valeurs obligatoires sont non vides ; `LEGAL_ENTITY_CAPITAL` est facultatif (entreprise individuelle) : exclu de la complétude, et les textes omettent « capital ... » s'il est vide. Hors dev, l'acceptation en ligne
  d'un document incomplet est refusée (« Ce document n'est pas encore finalisé. ») ; en dev, un bandeau
  « BROUILLON : informations de l'éditeur manquantes » s'affiche. Aucun crochet ne s'affiche jamais (valeur
  manquante : « (à renseigner) »).
- **Pages publiques** : `/partenaires/d/<jeton>/` (lecture + formulaire) et `.../accepter/` (POST). Jeton
  inconnu, expiré ou révoqué : le même 404. Limite par IP, CSRF normal, en-têtes `noindex`, `no-store`,
  `same-origin` (et non `no-referrer` : il ferait envoyer `Origin: null` au formulaire, donc un 403 CSRF). Le jeton est hors des journaux de l'application et n'est stocké que haché.
- **Acceptation** : case obligatoire + nom complet (+ case facultative distincte « citer ma boutique » pour la
  lettre d'essai, jamais pré-cochée). Elle fige le texte, son empreinte, le nom, l'empreinte salée de l'IP ;
  elle est **immuable** (ni modification ni suppression, y compris dans le Django admin). Double envoi :
  une seule acceptation.
- **Effets** : lettre d'essai = phase essai (30 jours) ; conditions = phase contrat (1 an), prise d'une place
  de fondateur, refus « Les places sont actuellement toutes attribuées. » s'il n'en reste plus. Les
  conditions ne sont proposées en ligne qu'après l'envoi du message « envoi_conditions » pendant l'essai.
- **Acceptation écrite** : saisie par l'équipe (référence du message obligatoire, date) ; mêmes effets,
  méthode « écrite ».

## Attribution (inchangée)

Lien `GET /r/<code>/` : code valide + partenaire actif + essai ou contrat en cours : clic enregistré,
cookie `hf_ref` (30 jours, HttpOnly, SameSite=Lax), 302 vers `/register/`. Sinon, même 302 sans cookie.
À l'inscription, le champ « Code partenaire » prime sur le cookie ; le rattachement est définitif ; un code
invalide, un prospect, un contrat expiré, une auto-attribution (même téléphone) ne changent rien à la
réponse ; plus de 3 vendeurs avec la même empreinte d'IP sur 7 jours sont signalés sans blocage. Un vendeur
inscrit pendant l'essai est attribué normalement.

## Commission

Point d'accroche : `subscriptions/services/payment.py::activate_subscription_from_payment` (webhook, retour
navigateur et tâche de vérification), isolé par un point de sauvegarde : une panne ne fait ni échouer ni
annuler l'activation.

```
net        = floor(montant payé x (100 - 1) / 100)
commission = floor(net x pourcentage du partenaire / 100)
```

Exemples : 2 000 -> 1 980 -> 594 ; 5 000 -> 4 950 -> 1 485 ; 2 999 -> 2 969 -> 890.

Une commission n'est créée que si **toutes** ces conditions sont vraies :

1. le partenaire est **sous contrat** (ou, le contrat terminé, il l'a été : droits acquis, article 6.3) ; un
   partenaire en essai ou en phase « aucune » ne gagne rien ;
2. une acceptation des **conditions du programme** existe ;
3. le paiement a été **encaissé à partir de l'acceptation** (jamais avant) : le premier paiement encaissé
   après l'acceptation fixe `first_paid_at` et la fenêtre de 12 mois ;
4. le paiement est réussi en base, hors test de paiement, de montant non nul, et sa ligne n'existe pas déjà.

Un vendeur inscrit pendant l'essai est attribué, mais ne génère aucune commission avant l'acceptation. Les
paiements d'avant l'acceptation ne sont jamais rattrapés (ni par `partners_reconcile`).

États : À valider, Validée, Versée, Annulée (annulation avec motif et audit ; une ligne versée ne
s'annule pas sans contrepartie). La validation du mois est toujours un geste humain.

## Contrat, places, seuil trimestriel

- 20 places de fondateur au plus, **sous contrat**, actives ou en pause ; une place libérée ne compte plus ;
  un prospect ou un partenaire en essai n'en occupe pas.
- Trimestres de 3 mois **à partir du début du contrat** ; un prospect ou un partenaire en essai n'est jamais
  jugé. Premier trimestre jamais manqué ; 1 manqué = avertissement ; 2 consécutifs = place libérable
  (action « Libérer la place », audit). Calcul à la lecture, aucune tâche planifiée.

## Versements, relevé, exports

Inchangés : cumul versable jusqu'à fin de mois, minimum 2 000 FCFA, échéance le 10 du mois suivant,
« Marquer comme payé » avec référence Orange (une fois). Le relevé WhatsApp et le CSV partenaire
n'indiquent jamais de nom, téléphone ni boutique (« Vendeur 1 · Medium · 11 mois restants »). L'export
interne est un fichier distinct. Neutralisation de l'injection de formules dans tous les CSV.

## Contacter un partenaire (WhatsApp)

Page équipe `/platform-admin/partenaires/contacter/` : indicatif (liste de `core/countries.py`, jamais
deviné), numéro, prénom, modèle (`invitation_essai`, `envoi_lettre_essai`, `envoi_conditions`, `relance`),
texte modifiable, aperçu. « Préparer le message » crée le prospect si besoin, génère le lien privé si le
texte contient `{lien}`, journalise le message (avec le lien **masqué**) et affiche un lien
`https://wa.me/<numéro>?text=<message encodé>` à ouvrir dans un nouvel onglet. **Aucun envoi automatique,
aucun appel réseau** : l'équipe touche « Envoyer » dans WhatsApp. Refus : numéro invalide, prénom vide,
variable non remplie (par exemple `{détail à compléter par le staff}`), message de plus de 1 000 caractères.

## Accès Pro offert pendant l'essai

Action « Offrir 30 jours de plan Pro » sur la fiche (POST, confirmation, une seule fois par vendeur) :
`Subscription.plan = pro` avec `expires_at = maintenant + 30 jours`, sur le compte vendeur ayant le numéro du
partenaire. Aucun nouveau modèle, aucune migration hors de l'app `partners`. Le plan retombe de lui-même
au gratuit à l'échéance ; aucun `SubscriptionPayment` n'est créé (ni CA, ni commission) ; audit avec le motif
« essai partenaire » ; refusé si le vendeur a déjà un abonnement payant actif, hors phase d'essai, ou sans
compte vendeur.

## Calculé à la lecture

Seuil trimestriel, activité, alertes, entonnoir, relevé : calculés à chaque affichage ; aucune tâche Celery
ajoutée.

## Limites connues

- Aucune vérification d'identité ; la lutte contre la fraude repose sur le signalement par IP,
  l'auto-attribution par téléphone et la validation humaine mensuelle.
- Une IP partagée (réseau mobile) peut signaler à tort des inscriptions : le signalement ne bloque rien.
- Le jeton d'un lien privé fait partie de l'URL : il peut apparaître dans les journaux d'accès du serveur web
  (Nginx) et dans les journaux du framework pour une réponse 404 ; il n'est jamais écrit par l'application.
- L'empreinte d'IP est salée avec `SECRET_KEY` : la changer remet à zéro le regroupement par IP.
- Les documents ne sont pas encore relus par un juriste et l'identité de l'éditeur n'est pas renseignée
  (F-106) ; la politique de confidentialité et les CGU ne mentionnent pas encore le cookie ni les données du
  programme (F-105).
- Les montants cités dans les documents juridiques figés (seuil, exemple de calcul) ne suivent pas
  `PlanConfig` : c'est voulu (clauses du contrat) ; le garde-fou « pas de tarif en dur » les exclut.
- Une commission annulée après versement exige une régularisation manuelle.

## Correction de la v1.0 en place (06/10)

L'éditeur est une entreprise individuelle (ABEXPERTISES), pas une SUARL : les textes v1.0 ont été corrigés
**en place** (variable `{{ entity.name }}`, capital facultatif) et l'empreinte du verrou mise à jour, car
aucune acceptation en ligne réelle n'avait eu lieu (démo seulement). **Toute modification d'un texte après
une acceptation réelle impose une v1.1** (nouveau gabarit, nouvelle constante), jamais une correction en
place.

## Bloc de clôture ajouté à la v1.0 en place (08/10)

Les trois documents se terminent maintenant par « Fin du document » et une ligne d'identification de
l'éditeur (valeurs vides omises proprement) ; la lettre d'essai et les conditions ajoutent un cadre
« Acceptation » (phrase d'explication, cases, nom complet, bouton « Accepter et envoyer »). Le texte figé
(`text_snapshot`) contient la clôture et le cadre sans les champs du formulaire, qui ne sont insérés que sur
la page publique. Corrigé **en place** (aucune acceptation réelle hors démo) et verrou SHA-256 mis à jour.
**Toute modification après une acceptation réelle impose une v1.1.**

## Page d'acceptation et preuve : corrections de la v1.0 en place (09/10)

- **Texte figé** (`text_snapshot`) : il s'arrête à la ligne d'identification. Le cadre « Acceptation », sa
  phrase d'explication et le formulaire n'en font plus partie (ils sont rendus par la page, avant
  acceptation). Les clauses de preuve des deux documents parlent désormais de « données techniques de
  connexion » et non plus d'« adresse IP ». Corrigé **en place** (aucune acceptation réelle hors démo) et
  verrou SHA-256 mis à jour. **Toute modification après une acceptation réelle impose une v1.1.**
- **Avant acceptation** : cadre « Acceptation » (hors snapshot) avec la phrase « En envoyant, vous acceptez ce
  document dans sa version X. Pour preuve de votre acceptation, HayaFlash conserve la date, l'heure, le texte
  accepté et des données techniques de connexion. Voir la politique de confidentialité. » au-dessus du bouton.
- **Après acceptation** (confirmation et réouverture du même lien) : page en lecture seule, imprimable :
  bandeau « Document important, à conserver », texte figé, bloc « Accepté par le partenaire » (nom saisi, date
  et heure en UTC « heure de Bamako (UTC) », version, autorisation de citer la boutique pour la lettre,
  référence = numéro d'acceptation + 12 premiers caractères de l'empreinte), sceau SVG en noir et blanc,
  référence répétée en pied de page à l'impression. Ce bloc vient de l'enregistrement `PartnerAcceptance`,
  jamais du snapshot. Aucun formulaire, aucune phrase d'explication, aucune mention d'IP.
- **Un jeton = une acceptation** : `PartnerAccessLink.acceptance` est renseigné à l'acceptation ; un second POST
  avec ce jeton est refusé (409, message en français, pas de doublon). Un lien d'acceptation sert donc à un
  seul document : les conditions du programme demandent un nouveau lien. L'IP ne bloque jamais une acceptation ;
  elle reste un signal interne (empreinte salée conservée pour examen humain). La limite de débit par IP des
  pages publiques (30 requêtes par minute) reste une protection contre l'énumération des jetons, pas un blocage
  d'acceptation.

## Sceau circulaire, QR et vérification publique (09/10)

- **Sceau** : SVG inline statique, noir et blanc, double cercle, texte sur arcs (en haut « HAYAFLASH · <nom de
  l'éditeur> », en bas « ACCEPTÉ · JJ MMM AAAA »), au centre « v<version> » et la référence, légère rotation
  (-2,5°). Il remplace le cadre rectangulaire dont le texte débordait. Rendu depuis `PartnerAcceptance`, jamais
  dans `text_snapshot`.
- **QR** (bibliothèque `qrcode==8.2`, déjà utilisée pour les QR des ventes ; SVG côté serveur) : il encode uniquement l'URL absolue `/verifier/<référence>/`
  (référence = numéro d'acceptation + 12 premiers caractères de l'empreinte). Aucun jeton privé, nom ou téléphone.
  À l'impression : 32 mm, avec la référence et l'URL en clair dessous.
- **Page `/verifier/<code>/`** (sans connexion, même limite de débit que les pages par lien privé, 404 neutre) :
  « Document authentique », type, version, date (heure de Bamako (UTC)), nom de boutique ou initiales du
  signataire, empreinte SHA-256 complète, statut Valide / Invalidé par HayaFlash. Jamais de téléphone, d'IP, de nom
  complet ni de texte du document.
- **Invalidation** (équipe, page Documents) : enregistrement `AcceptanceInvalidation` immuable avec motif
  interne ; rien n'est supprimé ni modifié.
- **Libellés** : « Accepté en ligne », « Vérifiable en ligne ». Jamais « signé », « signature électronique »,
  « certifié ».

## Migrations de l'app `partners` : règle « 0002 après staging » (F-113)

- Tant que `0001_initial` n'a été appliquée **nulle part** hors base de test jetable, on peut la régénérer.
- **0001 est gelée** (commit du programme partenaires). Dès qu'elle a été appliquée quelque part (poste local compris,
  staging, production), **on n'y touche plus** : toute évolution du schéma passe par une migration `0002`, puis `0003`...,
  **additive** (nouvelles tables, colonnes nulles ou avec valeur par défaut, index) et **réversible** (`migrate partners 000N-1`
  doit fonctionner). Aucun renommage ni suppression de colonne sans migration en deux temps. Régénérer 0001 sur une base où elle est
  déjà marquée appliquée casse cette base (colonnes manquantes : `migrate` ne rejoue pas la migration).
- Dépannage d'une base **locale** cassée par une régénération (données de démonstration seulement) :
  `python manage.py migrate partners zero --settings=config.settings.dev`, puis
  `python manage.py migrate partners --settings=config.settings.dev` et `seed_partners_demo`. Jamais sur staging ou production.


- **Contrôle fait le 09/10** (`sqlmigrate partners 0001`, PostgreSQL) : la migration crée 9 tables et 29 index, puis ajoute
  17 contraintes (14 clés étrangères, 2 unicités, 1 contrainte de contrôle) **sur les seules tables `partners_*` qu'elle
  vient de créer**. Aucun `ALTER`, `DROP`, `UPDATE` ni `INSERT` sur `accounts`, `subscriptions`, `orders` ou toute autre
  table existante. Elle dépend de `accounts.0007` et `subscriptions.0009` (clés étrangères vers `SellerProfile`,
  `SubscriptionPayment` et `User`).
