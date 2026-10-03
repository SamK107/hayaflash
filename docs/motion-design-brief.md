# HayaFlash — Brief motion design (inventaire factuel)

> Rédigé le 03/10/2026 à partir du **code du dépôt uniquement** (branche courante, release `v1.0.0-rc1` en préparation).
> L'application **n'a pas été lancée** pour écrire ce document : tout vient de la lecture du code. Aucun accès au VPS.
> Règle suivie : si une information n'est pas dans le code → **« non trouvé »**.
> Public visé par les vidéos : vendeurs et lanceurs de live au Mali et en Afrique de l'Ouest, souvent peu à l'aise avec le téléphone et l'ordinateur. Formats : 9:16 et 16:9.

---

## 0. À lire d'abord — les pièges à ne PAS montrer ou dire

| # | Piège | Pourquoi |
|---|-------|----------|
| 1 | **Ne pas promettre que le numéro du client est caché.** | Le numéro est affiché **en clair** au vendeur (commandes, livraisons, export CSV, réservations). Aucun masquage dans le code. |
| 2 | **Ne pas montrer de vidéo « en direct » dans l'app.** | HayaFlash n'a pas de vidéo live. Le live reste sur TikTok / Facebook ; HayaFlash fournit le lien et le QR code. |
| 3 | **Ne pas montrer le bouton « Livrée » ni « Échec » sur la page Livraisons.** | Les boutons ne s'affichent jamais (bug de code, voir §8 E-04). Pour marquer « Livré et payé », utiliser la page **Commandes**. |
| 4 | **Ne pas parler d'« annuler une commande ».** | Aucun bouton d'annulation côté vendeur ni côté acheteur, alors que deux textes le suggèrent. |
| 5 | **Ne pas parler de « Plafond de commandes » comme d'une limite active.** | Le champ existe mais **n'est pas appliqué**. |
| 6 | **Ne pas vendre comme « inclus dans Pro » : tableau LIVE, SMS automatiques, support WhatsApp prioritaire, nouveautés en avant-première.** | Ces points sont écrits dans la liste du plan Pro mais ne sont **pas bloqués par plan** (ou n'ont pas de code). Seules les **statistiques** sont réellement réservées à Medium/Pro. |
| 7 | **Ne pas montrer la page Statistiques en passant par un menu.** | Elle n'est liée à aucun menu. Adresse directe : `/seller/flash-sales/analytics/`. |
| 8 | **Ne pas dire « paiement en ligne » pour l'acheteur.** | L'acheteur paie **à la livraison** (espèces ou mobile money). Le vendeur paie son abonnement **uniquement par Orange Money** (Moov et Wave : « Bientôt »). |
| 9 | **Ne pas utiliser les témoignages de la page d'accueil ni les chiffres « 3× plus vite », « 2 heures par vente ».** | Origine **non trouvée**. |
| 10 | **Ne pas dire « 30 secondes pour programmer »** sans précaution. | L'accueil dit « 30 s », le tableau de bord dit « moins de 60 secondes ». Choisir une seule formulation et la valider. |
| 11 | **Ne pas dire que le vendeur doit montrer son visage ou donner son nom.** C'est vrai (rien d'obligatoire), mais ne pas dire que la bio ou la photo est visible sur la page boutique : elle ne l'est pas. | Voir §4. |
| 12 | **Ne pas citer « Premium ».** | Ce mot n'existe nulle part. Les plans s'appellent **Gratuit, Medium, Pro**. |
| 13 | **Tarifs : à confirmer en base de production avant publication.** | Les prix viennent d'une table modifiable depuis l'admin (`PlanConfig`). Les valeurs ci-dessous sont celles de départ du code. |

### Vocabulaire simple conseillé pour les vidéos (suggestion de rédaction, pas dans le code)

| Mot de l'app | Dit plus simplement |
|--------------|---------------------|
| COD / « COD a collecter » | « argent à récupérer à la livraison » |
| CA / « CA encaissé » | « argent déjà reçu » |
| « Clôturer la vente » | « terminer la vente » |
| « Réservations » (vendeur) | « clients qui veulent être prévenus » |
| « Teaser / Aperçus » | « annonce avant l'ouverture » |

---

## 1. Parcours et pages

Légende : **Rôle** = qui voit l'écran. Les libellés sont recopiés du code (accents manquants conservés quand ils sont dans l'app).

### 1.1 Inscription — `/register/`
- **Rôle** : tout visiteur.
- **Titre** « Créer mon compte » ; sous-titre « Gratuit · Prêt en 1 minute · Aucune carte requise ».
- **Champs** : « Nom de votre boutique » (ex. « Ex : Boutique Aminata Mode ») · « Numéro de téléphone » (ex. « +223 70 00 00 00 », aide « Avec indicatif pays. Ex : +223 pour le Mali. ») · « Mot de passe » (« Minimum 6 caractères ») · « Confirmer le mot de passe » · case « J'accepte les CGU et la Politique de confidentialité ».
- **Bouton** « Créer mon compte » (en cours : « Création en cours... »). Lien « Déjà un compte ? Se connecter ». Pied de page « HayaFlash · Bamako, Mali ».
- **Pas d'e-mail, pas de code SMS.** Un numéro sans « + » reçoit « +223 » devant (le 0 initial est retiré).
- **Succès** : connexion automatique → `/seller/`, message « Bienvenue ! Votre boutique '<nom>' est prete. »
- **Erreurs** : « Le numéro de téléphone est obligatoire. » · « Le nom de votre boutique est obligatoire. » · « Le mot de passe doit contenir au moins 6 caractères. » · « Les deux mots de passe ne correspondent pas. » · « Vous devez accepter les CGU et la politique de confidentialité. » · « Ce numéro est déjà utilisé. Connectez-vous ou utilisez un autre numéro. » · « Trop d'inscriptions depuis ce réseau. Réessayez plus tard. » · anti-robot : « Impossible de créer le compte pour le moment. Vérifiez vos informations et réessayez. » (si le formulaire est envoyé en moins de 3 secondes).

### 1.2 Connexion — `/login/`
- **Titre** « Connexion » ; « Accès à votre espace vendeur. » ; champs « Numéro de téléphone », « Mot de passe » ; bouton « Se connecter » (« Connexion... ») ; lien « Pas encore de compte ? Créer un compte gratuit ».
- **Erreurs** : « Veuillez renseigner votre téléphone et votre mot de passe. » · « Numéro de téléphone ou mot de passe incorrect. » · « Trop de tentatives. Réessayez dans quelques minutes. »
- **Blocage** après 5 échecs (téléphone + réseau) pendant 30 min : page « Connexion temporairement bloquée », bouton « Retour à la connexion ». Message : « Trop de tentatives. Réessayez dans 30 minutes ou contactez le support WhatsApp depuis votre numéro inscrit. »
- **Mot de passe oublié : non trouvé** (procédure manuelle via le support, finding F-23).

### 1.3 Menu vendeur (haut de page)
« Mes ventes » (ouvre le **tableau de bord** `/seller/`) · « Nouvelle vente » · « Commandes » · « Livraisons » · « Réservations » (avec compteur) · indicateur LIVE · menu compte : Profil, Paramètres, Déconnexion. « Pilotage HayaFlash » : réservé au personnel HayaFlash.
**Absents du menu : Statistiques et Abonnement.** L'abonnement s'atteint par Paramètres → « Passer Pro » (seulement si pas déjà Pro) ou par les fenêtres de quota.

### 1.4 Tableau de bord — `/seller/`
- « Bonjour, {nom} 👋 » · « Gérez vos ventes flash depuis votre tableau de bord. » · bouton « Nouvelle vente ».
- Cartes : « Commandes totales », « Ventes actives », « Ventes terminées » (⚠ ces deux dernières sont plafonnées à 5 et 3 : chiffres trompeurs, ne pas les montrer comme vrais totaux).
- Sections « Ventes à venir / en cours » (badges LIVE / Programmée), « Ventes récentes », lien « Voir toutes mes ventes → ».
- **Vide** : « Lancez votre première vente flash ! » · « Créez une vente en moins de 60 secondes et commencez à recevoir des commandes. » · bouton « Créer ma première vente ».
- Compte sans boutique : « Ce compte n'a pas de boutique ».

### 1.5 Liste « Mes ventes flash » — `/seller/flash-sales/`
- Onglets : « Programmées / En cours / Traitement / Terminées ».
- **Vides** : « Aucune vente programmée. » · « Aucune vente en cours. » · « Aucune vente en traitement. » · « Aucune vente terminée. »
- Badges : LIVE · Programmée · Fermée · En exécution · Terminée · Annulée.
- Bandeau quota : « Plan Gratuit · X/3 ventes ce mois-ci » / « Dernière disponible ».
- **Limite atteinte** : « Limite du plan Gratuit atteinte » · « Vous avez utilisé 3/3 ventes ce mois-ci. Plan Pro : ventes flash illimitées. » · bouton « Voir les plans » · « Quota remis à zéro le 1er du mois prochain ».
- Fenêtre « Choisissez votre plan » · « Débloquez plus de ventes et de fonctionnalités. » · « Choisir Medium — 2 000 FCFA/mois » · « Choisir Pro — 5 000 FCFA/mois » (Pro « Recommande ») · « Paiement via Orange Money · Sans engagement » · « Continuer avec le plan Gratuit ».
- Page `quota_exceeded` (sur `/create/`) : « Limite mensuelle atteinte », boutons « Passer a Medium » / « Passer a Pro » (Medium y est « Recommande »).

### 1.6 Création de vente — `/seller/flash-sales/create/`
Détail des champs et du flux : §2.3.

### 1.7 Fiche d'une vente — `/seller/flash-sales/<n°>/`
- Blocs : Début · Fin · Zone de livraison · Plafond commandes.
- « Produits (N) » avec « Publication rapide » et « Ajouter » (visibles seulement si la vente est « programmée »). Ligne produit : « X FCFA · unité » + barre de stock. **Vide** : « Aucun produit ajouté. » / « Ajouter le premier produit ».
- **Actions selon l'état** :
  - À venir : « Ouvrir la vente » (confirmation « Ouvrir la vente maintenant ? ») · « Modifier » · « Annuler la vente » (« Annuler cette vente ? »). Si impossible : « Cette vente ne peut pas s'ouvrir : … ».
  - En cours : « Tableau LIVE » · « Fermer la vente » (« Fermer la vente maintenant ? »).
  - Heure de fin passée, vente non clôturée : « L'heure de fin est passée : les commandes ne sont plus acceptées. Clôturez la vente pour passer au traitement des commandes. » + bouton « Clôturer la vente ».
  - Terminée : « Reprendre cette vente » (« Reprendre cette vente ? Une copie sera créée avec les mêmes produits. ») · « Voir les commandes » · « Exporter CSV ».
- **Lien de partage** : adresse `/f/<slug>/` + bouton copier + « QR Code » → fenêtre « Scannez pour commander » / « Idéal pour vos lives TikTok / Facebook » / « Fermer ».
- Messages : « Vente ouverte ! Les commandes sont acceptées. » · « Vente fermée. » · « Vente annulée. » · « Vente mise à jour. » · « Vente clonee ! Modifiez les dates puis ouvrez-la. »
- Erreurs : « Impossible d'annuler une vente en cours. Fermez-la d'abord. » · « Impossible d'ouvrir une vente avec le statut '…' ».
- Ouvrir avant l'heure : l'heure de début passe à maintenant, la durée est conservée.
- Badge « N réservation(s) » (clients à prévenir).

### 1.8 Publication rapide — `/seller/flash-sales/<n°>/quick-publish/`
Détail : §2.4.

### 1.9 Ajout de produit classique — `/seller/flash-sales/<n°>/products/create/`
Détail : §2.5.

### 1.10 Suivi des commandes — `/orders/seller/dashboard/`
- Titre « Dashboard LIVE ». Vente en cours : bandeau LIVE + titre + compte à rebours.
- Chiffres (rafraîchis toutes les 4 s) : « Commandes », « Articles livrés », « FCFA encaissé », « FCFA en cours » ; « Stock critique : X — N restant(s) ».
- Liste « Commandes » : « Confirmez ici · Livraisons détaillées dans Livraisons » ; « Actualisation auto » (toutes les 3 s).
- **Carte commande** : nom et **téléphone du client en clair**, badge d'état (**En attente → Confirmé → En livraison → Livré et payé**, ou Annulé), articles « x2 », « Total ». **Un seul bouton**, nommé d'après l'**étape suivante** : « Confirmé », puis « En livraison », puis « Livré et payé ».
- **Vide** : « Aucune commande pour l'instant » / « Les nouvelles commandes apparaissent ici automatiquement ».
- Fermeture : fenêtre « Fermer la vente ? » · « Plus aucune commande ne sera acceptée. Cette action est définitive. » · « Annuler » / « Fermer » ; lien « Voir la vente ».
- Pas de vente en cours : « Prochaine vente » / « Début : … » / « avant ouverture automatique » ; ou « Aucune vente active » · « Créez une vente flash pour voir votre dashboard LIVE ici. » · « Créer une vente ».
- Limites : **20 dernières commandes** (toutes ventes confondues, tous plans). Pas de bouton annuler. Passer à « Livré et payé » met aussi la livraison en « encaissé ».
- Export CSV : colonnes #, Client, Téléphone, Produits, Total FCFA, Statut, Heure.

### 1.11 Livraisons — `/orders/seller/deliveries/`
- « Livraisons » · « Logistique post-vente · Préparez, livrez, encaissez » · lien « Dashboard » · liste « -- Sélectionnez une vente -- ».
- Chiffres : « Commandes », « COD a collecter », « COD collecte », « En attente », « En cours », « Livrées ». Filtres : Toutes / En attente / En cours / Livrées / Annulées (⚠ « Annulées » filtre en réalité les « Échec livraison »). Rafraîchi toutes les 10 s.
- États d'une livraison : En attente · Livreur assigné · En livraison · Livré · Échec livraison.
- Ligne : nom, téléphone, adresse (80 caractères max), lecteur « Message vocal du client », « X FCFA a collecter » ou « ✓ collecte », « Livreur : … », liens « Maps » / « Waze », boutons « Confirmer », champ « Nom du livreur » + « En livraison », « Livrée », « Échec ».
- **Vides** : « Aucune livraison pour ce filtre. » · « Sélectionnez une vente pour voir ses livraisons. »
- ⚠ **« Livrée » et « Échec » ne s'affichent jamais** (E-04). ⚠ Le bouton « En livraison » est un envoi de formulaire classique qui risque d'afficher un morceau de page brut au lieu de revenir à la liste (à vérifier, non exécuté).

### 1.12 Performances / statistiques — `/seller/flash-sales/analytics/`
- **Gratuit ou plan expiré** : « Statistiques avancées » · « Accédez au reporting complet avec les plans MEDIUM ou PRO. » · bouton « Voir les offres ».
- **Medium et Pro** : « Statistiques » + badge du plan ; cartes « Commandes livrées », « CA encaissé », « Articles livrés », « CA en attente » ; graphique « CA — 30 derniers jours » ; « Top produits » (« N vendus »).
- **Medium seulement** : encart « Graphiques annuels disponibles en PRO » · « Historique complet, CA par vente flash, évolution mensuelle. » · « Passer au PRO — 5 000 FCFA/mois ». (⚠ « CA par vente flash » : **non trouvé** dans la page Pro.)
- **Pro** : en plus « CA mensuel — 12 mois ».
- **Accès : aucun lien de menu** (E-01).

### 1.13 Abonnement — `/seller/abonnement/`
- « Mon abonnement » · « Plan actuel » · « Expire le jj/mm/aaaa » ou « Actif » · « Ventes ce mois-ci X / Y » · « Limite atteinte. »
- « Passer à un plan supérieur » : cartes Medium et Pro, « X FCFA / mois », « Recommande » sur Pro, boutons « Choisir Medium » / « Choisir Pro ».
- Si Pro : « Vous êtes sur le plan Pro » · « ventes flash illimitées, toutes les fonctionnalités activées. » · « Renouveler ».
- « Historique des paiements » · pied « Paiement sécurisé via Orange Money · Sans engagement mensuel ».
- **Paiement** (`/seller/abonnement/checkout/<plan>/`) : « Paiement plan Pro » · « Plan choisi » / « Montant » · « Mode de paiement » : Orange Money actif ; « Moov Money » et « Wave » = « Bientôt disponible » / « Bientôt » · « Votre numéro Orange Money * » (préfixe +223, ex. « 70 00 00 00 ») · « Vous serez redirigé vers la page de paiement Orange Money pour saisir votre code PIN. » · « Paiement sécurisé par Orange Money · Accès immédiat à l'activation » · bouton « Payer X FCFA via Orange Money » · « Annuler ». Bandeau possible « Tarif spécial : … ».
- **En attente** : « Paiement en cours de traitement » · « Vérifier le statut » · rechargement automatique toutes les 10 s · « Problème ? Contactez-nous sur WhatsApp avec la référence … ».
- Messages : « Paiement confirmé ! Votre plan Medium est actif. » · « Paiement annulé. » · erreurs « Le numéro de téléphone est obligatoire. » · « Le paiement Orange Money n'a pas pu être initié. » · « Le paiement via Moov/Wave sera disponible prochainement… »
- ⚠ Plan expiré : la page peut encore afficher « Plan actuel : Pro/Medium » sans date (E-12).

### 1.14 Page publique d'une vente (acheteur) — `/f/<slug>/`
Trois états. **Aucun compte requis pour l'acheteur.**

**a) Avant l'ouverture (« BIENTÔT »)**
- Photo de couverture, nom de la boutique, titre, description + audio du vendeur + bouton « Écouter » (lecture vocale du texte écrit par le navigateur, en français).
- « Ouverture dans h:min:sec » / « Ouverture le jj/mm à HHhMM ». « Au programme » (annonces) · « N article(s) disponible(s) dès l'ouverture » · zone de livraison.
- Boutons « M'alerter à l'ouverture », « Partager cette vente » (WhatsApp), « Partager ». Preuve sociale « N personnes attendent l'ouverture » (seulement à partir de 3).
- Fenêtre « Me prévenir dès l'ouverture » · « {vendeur} vous appellera dès que la vente s'ouvre. » · « Votre nom » · « Votre téléphone * » · « ✓ Je veux être prévenu(e) » · « C'est noté ! ». ⚠ « vous appellera » n'est pas garanti par l'application (E-09).

**b) Vente en cours (« EN DIRECT »)**
- « Ferme dans hh:mm:ss » · « N commande(s) · N ces 10 dernières min » / « Dernière commande il y a N min » · nom de la boutique, titre, zone, dates, « N produit(s) ».
- **Carte produit** : photo (agrandissable), nom, description, audio, prix « X FCFA », stock (« Plus que N ! » si ≤ 5, « N restant(s) », « Épuisé »), bouton « Commander · X FCFA ».
- « Partager sur WhatsApp » / « Partager » · pied « Propulsé par HayaFlash · Mali ».
- **Tiroir de commande** : produit + prix ; « Quantité » (− / +) ; « Stock disponible : N » ; si déjà commandé avant : « Vos coordonnées de la dernière commande sont pré-remplies. » / « Pas vous ? » ; « Votre nom » (ex. « Ex: Mariam Kone ») ; « Téléphone * » (« Le vendeur vous appelle sur ce numéro pour la livraison ») ; « Adresse de livraison (ou message vocal ci-dessous) » (« Quartier, rue, point de repère… ») ; « Envoyer ma position » → « Position envoyée (précision ~N m) » ou « Localisation refusée — votre adresse écrite suffit pour la livraison. » ; « Enregistrer un message pour le vendeur » → « Enregistrement en cours… » → « Votre message vocal : » ; « Note au vendeur (optionnel) » ; « Total estime » ; « Paiement a la livraison — Espèces ou mobile money » ; bouton « Confirmer la commande » (« Envoi en cours... »).
- **Succès** : « Commande envoyée ! » · « Vous serez contacte au {tel} » · « Le vendeur vous appellera pour confirmer la livraison. » · « Continuer les achats ».
- **Erreurs** : « Le numéro de téléphone est obligatoire. » · « Indiquez votre adresse (par ecrit ou en message vocal). » · « Connexion impossible. Verifiez votre reseau. » · « Une erreur est survenue. » ⚠ Certains messages du serveur restent en **anglais** sur cette branche (E-14).
- Mention « Paiement a la livraison · Annulation possible avant livraison » : **aucune annulation n'existe** (E-02).

**c) Vente terminée**
- « Vente terminée » · « Terminée le … · {boutique} » · statistiques (« article(s) vendu(s) en N min », « clients servis », « personne(s) en attente de la prochaine ») · carte « prochaine vente » · « Merci d'avoir participé à cette vente flash ! » · « À très bientôt chez {vendeur} 🙏 » · « M'alerter pour la prochaine vente » (fenêtre « Être alerté(e) en premier ») · lien « Voir toutes les ventes en direct et à venir → ».
- Ce dernier lien est **absent de la page en cours** (F-64).

### 1.15 Autres pages publiques
- **`/ventes/`** : « Ventes flash » · « En direct et à venir · touchez une vente pour voir les produits » · groupes « En direct », « Bientôt » (< 1 h), « Aujourd'hui », « Demain », puis « Lundi jj/mm » · ligne : avatar ou initiale, nom boutique, catégorie · titre, « En direct » / « jusqu'à HH:MM » · rafraîchi toutes les 45 s. **Vide** : « Aucune vente en ce moment » / « Les prochaines ventes flash apparaîtront ici dès qu'elles seront programmées. »
- **`/s/<slug>/`** (boutique) : « HAYAFLASH » / « Toutes les ventes » · nom de boutique · « Boutique officielle sur HayaFlash » · « Commandes » / « Articles vendus » · « Ventes en cours », « Prochainement » (« Être alerté à l'ouverture ») · vide « Aucune vente en cours ni programmée pour le moment. » · boutons de partage. **Bio et photo : non affichées ici.**
- **`/confidentialite/`**, **`/cgu/`**, **`/mentions-legales/`** : textes légaux.

### 1.16 Profil et paramètres
- **Profil** (`/seller/profil/`) : « Mon profil » · « Ce que vos clients voient » · « Aperçu boutique » · « Photo de profil » (JPG/PNG, 5 Mo max) · « Nom d'affichage * » · « Nom commercial » (« Affiché sur votre page boutique et les partages WhatsApp ») · « Téléphone » (non modifiable) · « Description » · « Zones de livraison » · « Type de produits vendus » · « Lien public de votre boutique ».
- **Paramètres** (`/seller/parametres/`) : « Mon abonnement » (Plan Gratuit/Medium/Pro, bouton « Passer Pro ») · teaser « Débloquez le Plan Pro » (ventes illimitées, Analytics avancés, SMS clients auto, Support prioritaire) · « Informations du compte » (Téléphone avec « Non vérifié » pour tous les vendeurs, Code vendeur « Copier », Membre depuis) · « Mot de passe » (« 8 caractères minimum » ≠ 6 à l'inscription) · « Zone danger » / « Déconnexion de tous les appareils ».

### 1.17 Réservations — `/seller/flash-sales/interests/` et `/<n°>/interests/`
Liste des clients qui ont demandé à être prévenus (nom, téléphone **en clair** avec lien d'appel), par vente. Remise à zéro possible. Détail des libellés : **non relevé en entier**.

---

## 2. Flux détaillés (étapes numérotées)

### 2.1 Créer un compte
1. Ouvrir la page d'inscription (`/register/`, bouton « Créer un compte gratuit » depuis la connexion).
2. Écrire « Nom de votre boutique ».
3. Écrire « Numéro de téléphone » (avec +223, ou sans : +223 est ajouté).
4. Écrire « Mot de passe » (6 caractères minimum) puis « Confirmer le mot de passe ».
5. Cocher « J'accepte les CGU et la Politique de confidentialité ».
6. Toucher « Créer mon compte ».
7. Arrivée sur le tableau de bord avec « Bienvenue ! Votre boutique '…' est prete. »

### 2.2 Se connecter
1. Ouvrir `/login/`.
2. « Numéro de téléphone » puis « Mot de passe ».
3. Toucher « Se connecter ». → tableau de bord.
Après 5 échecs : blocage 30 minutes.

### 2.3 Lancer une vente (1 h / 2 h / personnalisée)
1. Menu « Nouvelle vente » (ou « Créer ma première vente »). Page « Programmer une vente flash » — « Tout se remplit ici — vos clients recevront un lien direct. »
2. « Titre de la vente * ».
3. (Option) « Description », ou « Description vocale » (enregistrement ; **pas de transcription** : la phrase « dicter en bambara, français, wolof… » veut dire *enregistrer sa voix*).
4. (Option) « APERÇUS » : une annonce par ligne, affichée avant l'ouverture sans révéler les produits.
5. « Date et heure de début * » (pas dans le passé, 5 min de tolérance).
6. « Durée de la vente * » : toucher **« 1 heure »** (« Urgence maximale ») ou **« 2 heures »** (« Maximum · Recommandé »), ou « + Durée personnalisée (entre 15 min et 2h) » puis écrire les minutes (15 à 120, ex. 90). L'« Heure de fin calculée » s'affiche.
7. (Option) « Type de produits » (Mode, Chaussures, Beauté, Électronique, Alimentation, Maison, Autre) · « Zone de livraison » · « Plafond de commandes » (⚠ non appliqué) · « Image de couverture (optionnelle) » via « Galerie » ou « Caméra ».
8. Toucher « Programmer la vente » (« Annuler » pour sortir). Message « Vente créée avec succès ! » → fiche de la vente.
9. Ajouter les produits (§2.4 ou §2.5).
10. Ouverture : **automatique à l'heure de début**, ou bouton « Ouvrir la vente » (confirmer).
11. Partager le lien `/f/<slug>/` (copier, WhatsApp, « QR Code »).
12. Fin : **automatique à l'heure de fin**, ou « Fermer la vente » / « Clôturer la vente ».

Règles qui bloquent : max 120 minutes · max **3 ventes par jour** (« Vous avez déjà 3 ventes ce jour-là. Maximum 3 ventes flash par jour. ») · quota mensuel du plan (§3).

### 2.4 Publication rapide
1. Depuis la fiche vente, toucher « Publication rapide ». Titre « Publication rapide ».
2. (Option) « Reprendre les produits d'une vente précédente : » → « Choisir une vente... » → « Reprendre » (10 dernières ventes).
3. (Option) « Photos (optionnel) » : glisser ou « parcourir » (5 Mo max par photo).
4. « + Nouveau produit » : remplir Nom (« Nom du produit »), Prix catalogue, Prix promo (vide = même prix), Stock, Ordre.
5. (Option) cocher des lignes puis « % Remise groupée » (remise en %) ou « Stock par défaut » (stock fixé).
6. Par ligne : « Masquer (sans supprimer) », « Réafficher ce produit », « Supprimer définitivement ».
7. Toucher « Publier N produit(s) » (« Publication... »). Message « N produit(s) publié(s). »
8. Vide : « Catalogue vide. Utilisez « Nouveau produit » ou l'upload de photos ci-dessus. »

### 2.5 Méthode classique (un produit à la fois)
1. Fiche vente → « Ajouter » (ou « Ajouter le premier produit »).
2. Page « Nouveau produit » : « Photo principale » (Galerie / Caméra) · « Nom du produit * » · « Description » (+ « Description vocale ») · « Prix (FCFA) * » · « Quantité disponible * » · « Unité » (ex. « piece ») · « Ordre d'affichage ».
3. Toucher « Ajouter le produit » → « Produit ajouté. » (modification : « Enregistrer » → « Produit mis à jour. »).

### 2.6 Suivre les commandes
1. Menu « Commandes » (ou « Tableau LIVE » depuis la vente).
2. Les nouvelles commandes arrivent seules (rafraîchi toutes les 3-4 s).
3. Sur chaque carte, toucher le bouton « Confirmé ».
4. Puis « En livraison ».
5. Puis « Livré et payé » (fin).
6. Fin de vente : « Fermer la vente » → « Fermer ». « Exporter CSV » depuis la fiche.

### 2.7 Exécuter les livraisons
1. Menu « Livraisons » → choisir la vente dans la liste.
2. Lire adresse, « Maps » / « Waze », écouter « Message vocal du client ».
3. Toucher « Confirmer ».
4. Écrire « Nom du livreur » puis « En livraison ».
5. Marquer livré / échec : **non fonctionnel (E-04)** — utiliser la page Commandes (« Livré et payé »).

### 2.8 Consulter les performances
1. Aucun lien de menu : ouvrir `/seller/flash-sales/analytics/`.
2. Plan Gratuit : écran « Statistiques avancées » + « Voir les offres ».
3. Medium/Pro : chiffres, « CA — 30 derniers jours », « Top produits » ; Pro : « CA mensuel — 12 mois ».

### 2.9 Souscrire un plan
1. Paramètres → « Passer Pro », ou « Voir les plans » / « Choisir Medium » / « Choisir Pro » depuis une fenêtre de quota.
2. Page paiement : vérifier « Plan choisi » et « Montant ».
3. Garder « Orange Money ».
4. Écrire « Votre numéro Orange Money * ».
5. Toucher « Payer X FCFA via Orange Money ».
6. Orange affiche sa page : saisir le **code PIN** chez Orange.
7. Retour sur HayaFlash : « Paiement en cours de traitement » (vérification auto toutes les 10 s, bouton « Vérifier le statut »).
8. « Paiement confirmé ! Votre plan … est actif. » Si annulation : « Paiement annulé. »

---

## 3. Règles métier réellement appliquées

| Sujet | Règle dans le code |
|-------|--------------------|
| Durée maximale d'une vente | **120 min** (2 h). Minimum pour une durée personnalisée : **15 min**. |
| Ventes par jour | **3 max** par jour de début (heure de Bamako), ventes annulées exclues. Vaut pour **tous les plans**. |
| Quota mensuel | Gratuit **3** · Medium **10** · Pro **illimité**. Compte les ventes **créées** depuis le 1er du mois, annulées exclues. Remise à zéro le 1er. |
| Si la vérification du quota échoue | La création est **refusée** (« Impossible de vérifier votre quota. Réessayez. »). |
| Prix (valeurs de départ, modifiables en admin, à confirmer en prod) | Gratuit **0** · Medium **2 000 FCFA** · Pro **5 000 FCFA**, pour **31 jours**. FCFA entiers. |
| Contenu Gratuit | Page publique vendeur · Commandes en ligne · Lien de partage WhatsApp. |
| Contenu Medium | Gratuit + « Statistiques de ventes (30 derniers jours) » + « Historique des commandes complet ». |
| Contenu Pro | « Statistiques et analyses avancées (historique complet) » · « Tableau de bord LIVE temps réel » · « Notifications SMS automatiques » · « Support prioritaire WhatsApp » · « Accès aux nouvelles fonctionnalités en avant-première ». |
| **Ce qui est réellement bloqué par plan** | **Uniquement les statistiques** (Medium/Pro) et le graphique annuel (Pro). Tout le reste est identique pour tous. |
| Ouverture / fermeture automatiques | Tâche planifiée **toutes les 60 s** : ouvre à l'heure de début, ferme à l'heure de fin. Les commandes sont de toute façon acceptées/refusées **selon l'heure**, même si la tâche a du retard. Dépend du bon fonctionnement du planificateur (F-20). |
| Rappel automatique | SMS aux inscrits ~1 h avant l'ouverture, **seulement si le service SMS est configuré**. Même règle pour tous les plans. |
| Paiement acheteur | **À la livraison uniquement** (espèces ou mobile money). Pas de paiement en ligne. |
| Stock | Retiré **dès la commande**, sans délai d'expiration (F-59). |
| Paiement de l'abonnement | **Orange Money seulement**. Moov et Wave : « Bientôt ». Pas de carte bancaire. |
| Renouvellement | **Manuel** (pas de prélèvement automatique). Même plan encore actif : la nouvelle période s'ajoute **à partir de la date d'expiration**. Autre plan : 31 jours à partir de maintenant (le reste de l'ancien plan est perdu). |
| Remboursement | Pas de remboursement d'une période payée, sauf double débit ou débit sans activation (CGU). |
| **À l'expiration du plan** | Aucune tâche de rétrogradation ni de rappel **trouvée**. Le plan expiré **compte comme Gratuit** : 3 ventes/mois, statistiques verrouillées. Mais l'écran Abonnement peut encore afficher l'ancien nom (E-12). |
| Tarif spécial | Possible par vendeur (≥ 100 FCFA, ≤ prix officiel, 30 jours max) créé par l'équipe HayaFlash ; refusé si abonnement payant actif. |
| Sécurité | Connexion : 10 essais/min par réseau, blocage 30 min après 5 échecs. Inscription : 5/h par réseau. Commandes : 10 par 10 min par numéro. |
| Fuseau horaire | Afrique/Bamako (UTC+0). Langue : français. |

---

## 4. Confidentialité — ce que voit chacun

### Ce que voit l'acheteur / le public
- Nom de la boutique : « Nom commercial », sinon « Nom d'affichage », sinon « Vendeur ».
- Titre, description, audio, photos, prix, stock restant, zone de livraison, dates et compte à rebours de la vente.
- Chiffres globaux (nombre de commandes, « N ces 10 dernières min », « N personnes attendent ») : **pas de nom ni de numéro d'acheteur**.
- **Numéro du vendeur : non affiché** sur les pages publiques lues. Le vendeur appelle le client depuis son propre téléphone.
- Bio et photo de profil : la politique de confidentialité dit que la bio est publique, mais **les pages publiques ne l'affichent pas** ; la photo n'apparaît que dans la liste `/ventes/`.

### Ce que voit le vendeur
- Nom, **numéro de téléphone en clair**, adresse, position GPS, message vocal et note de chaque client : Commandes, Livraisons, export CSV, Réservations (lien d'appel).

### Numéro du client masqué ?
- **NON. Nulle part.** Ni côté vendeur, ni dans l'export, ni pour l'équipe HayaFlash (administration). Les journaux techniques écrivent aussi des numéros (F-36).
- ⚠ **À ne pas utiliser comme argument marketing** : « numéro caché », « vos clients restent anonymes », « le vendeur ne voit pas le numéro ».
- Côté acheteur, le navigateur mémorise nom/téléphone/adresse pour pré-remplir la prochaine commande (stockage local du téléphone de l'acheteur, bouton « Pas vous ? »).

### Visage ou nom du vendeur obligatoire ?
- **Non.** L'inscription demande seulement : nom de boutique, téléphone, mot de passe. Aucune photo ni pièce d'identité exigée. La photo de profil est facultative. L'application ne contient **aucune vidéo** du vendeur.
- Un nom de boutique (ou « Vendeur ») est toujours visible pour l'acheteur, donc une vente n'est pas « totalement anonyme ».

### Non encore vrai (ne pas utiliser)
- Numéro masqué · vérification de téléphone (le code SMS existe mais est inactif : « Non vérifié » pour tout le monde) · annulation par l'acheteur · « le vendeur est appelé automatiquement » · bio publique visible.

---

## 5. Identité visuelle

### Couleurs (codes hexadécimaux)
- **Principale : #FF4D2E** (orange-rouge « flash »). ⚠ `CLAUDE.md` indique #E63946 : c'est **faux** ; le code et `docs/FRONTEND_VENDORING.md` donnent #FF4D2E.
- Compléments : or **#FFB800** · noir **#111111** · succès **#22C55E** · alerte **#F59E0B** · danger **#EF4444** · gris texte **#6B7280** · fond **#F5F5F5**.
- Page d'accueil : flash #FF4D2E · violet **#5B2EFF** · citron **#F9F871** · fond sombre **#1A1A2E** · clair **#FAFAFA**.
- Pastilles d'icônes : #6556D6, #0F857A, #1E8A4C, #2F6BD8, #A5660B, #475569.
- Dégradé du logo : **#FFC24A → #FF8A2B → #FF4D2E**.
- Application installable (PWA) : couleur de thème #FF4D2E ; fond #1A1A2E (vendeur) / #FF4D2E (acheteur).

### Polices
- **Inter** 400 à 800 (textes de l'application) et **Poppins** 700 à 900 (grands titres de l'accueil). Fichiers dans `static/fonts/`.

### Logos et icônes (chemins)
- `static/img/brand/bolt.svg` (éclair) · `logo.svg` · `logo-dark.svg` · `logo.png` · `logo-dark.png`.
- Icônes d'appli : `static/img/icon-192.png`, `icon-512.png`, `icon-1024.png`, `icon-seller-maskable-*`, `icon-buyer-*`, `icon-buyer-maskable-*`, `apple-touch-icon.png`, `apple-touch-icon-buyer.png`, `favicon.ico`.
- Image de partage : `static/img/og-default.png` (1200×630). Scripts de génération : `scripts/generate_og_image.py`, `scripts/generate_pwa_icons.py`.
- Icônes d'interface : **Lucide 0.462.0** (dans `static/vendor/`).
- Proposition de logo (non adoptée, à ne pas utiliser) : `Claude outputs/hayaflash-logo-proposition.svg/.png`.
- Noms d'appli : vendeur « HayaFlash » (ouvre `/seller/`) ; acheteur « HayaFlash — Ventes flash » (ouvre `/ventes/`), description « Les ventes flash des boutiques près de chez vous ».

### Ton des textes
Vouvoiement, phrases courtes, orienté bénéfice, énergique. Slogans trouvés : « Programmez. Vendez. Haya s'occupe du reste. » · « Vendez fort. Gérez léger. » · « 1 heure de vente. 0 minute perdue. » · « Ventes flash professionnelles ».

### Page d'accueil (`templates/core/home.html`)
- Section problème « Reconnaissez-vous ça ? » (6 questions) · 4 étapes **Programmez / Recevez / Livrez / Pilotez** · cartes de fonctions · 5 « gains » · FAQ · « PASSEZ AU SÉRIEUX » · « Pas de boutique ? Pas de problème. »
- 3 témoignages (Fatoumata T., Modibo K., Aminata D.) — **origine non trouvée**.
- Affirmations à vérifier avant usage : « 30 s pour programmer » · « 100% sans app à installer » · « Vous confirmez ou annulez en un tap » (annulation absente) · « Livraisons groupées automatiquement » (non trouvé) · « Recettes, taux de livraison, best-sellers, clients fidèles » (partiellement trouvé).

### Composants récurrents
Cartes très arrondies · pastilles (badges) · point LIVE qui pulse · tiroir de commande qui monte du bas · barres de stock · petits messages (toasts) en bas · bandeau « Hors ligne — vérifiez votre connexion » · bouton « Installer » (appli) · bouton vert WhatsApp · pastilles d'icônes colorées.

---

## 6. Support de capture — script Playwright

### Mode d'emploi
1. Lancer le site **en local** (`python manage.py runserver --settings=config.settings.dev`), avec une base de démonstration **vierge** : définir `DEV_SQLITE_NAME` (par ex. `demo_motion.sqlite3`) **à l'identique** pour le serveur et pour le script. Une base neuve par exécution (limite 3 ventes/jour par compte).
2. `pip install playwright pillow` puis `playwright install chromium`.
3. `python scripts/motion_capture_demo.py --project-dir . --out motion_assets --format vertical` (1080×1920) ; `--format horizontal` (1920×1080) ; `--format both` ; `--headed` pour voir le navigateur. Enregistrer le script ci-dessous sous `scripts/motion_capture_demo.py`.
4. Résultats : dossier de captures PNG + `manifest.json`.

### Garde-fous inclus
Refuse tout hôte autre que local · refuse de tourner sans `manage.py` · refuse si `ORANGE_SMS_API_KEY` est définie (pas d'envoi SMS réel) · **ne clique jamais** sur « Payer … via Orange Money ».

### Données fictives
Vendeurs `+22370000901` (« Boutique Démo Aminata ») et `+22370000902` (« Boutique Démo Moussa») · acheteurs `+22370000101` à `103` · produits : Pagne wax 7 500 (promo 6 000, stock 20), Sac à main rouge 12 000 (promo 9 500, stock 8), Sandales femme 5 000 (stock 15), Bracelet perles 3 000 (stock 12, ajout classique) · mot de passe `DemoMotion!2026`. ⚠ Ces numéros pourraient appartenir à de vraies personnes : ne jamais envoyer de SMS réel.

### Écrans capturés
Accueil (défilement) · calendrier vide · inscription · écrans vides (liste, abonnement, paiement Pro, statistiques verrouillées, commandes sans vente) · création de vente (durée personnalisée puis 1 h) · publication rapide · ajout classique · page d'attente + « M'alerter » · ouverture + QR + calendrier · 3 commandes acheteurs · tableau Commandes (avancement des états) · Livraisons · fermeture + page « Vente terminée » · écrans Medium et Pro (abonnement, statistiques) · tableau de bord, liste, profil, paramètres, réservations.

### Points de fragilité (script **non exécuté**)
- Les sélecteurs reposent sur des placeholders et des identifiants lus dans le code ; un changement de texte peut casser une étape (le script enregistre l'erreur et **continue**).
- Les lignes de la publication rapide s'insèrent **en haut** de la liste.
- Le bouton « En livraison » (formulaire classique) peut afficher un fragment (voir E-04).
- Le bouton « M'alerter » peut demander l'autorisation de notifications ; la bannière « Installer » peut apparaître : à masquer au montage.
- Pas besoin du planificateur Celery : le script ouvre/ferme la vente à la main.
- Les captures « Livrée / Échec » **n'existent pas** (boutons absents).

### Script

```python
#!/usr/bin/env python3
"""HayaFlash — captures d'écran pour le motion design, avec DONNÉES 100 % FICTIVES.

Ce que fait le script (dans l'ordre) :
  1. crée un compte vendeur de démo (ou s'y reconnecte) via l'interface réelle ;
  2. programme une vente flash, ajoute des produits (Publication rapide + méthode classique) ;
  3. simule 3 acheteurs fictifs qui commandent sur la page publique ;
  4. fait avancer les commandes et les livraisons côté vendeur ;
  5. passe le compte démo en Gratuit / Medium / Pro (via `manage.py shell`, en local) pour
     capturer les écrans Statistiques et Abonnement dans chaque état ;
  6. enregistre toutes les images + un manifest.json (liste des écrans, URL, erreurs).

Formats :
  vertical   : téléphone 360x640 CSS px, facteur 3  -> PNG de 1080x1920 (9:16)
  horizontal : bureau 1920x1080, facteur 1          -> PNG de 1920x1080 (16:9)
               (les écrans ACHETEUR restent en format téléphone : à placer dans un cadre de téléphone)

SÉCURITÉ : le script refuse de tourner contre autre chose que localhost / 127.0.0.1.
Ne jamais le lancer contre staging ou la production (il crée des comptes, des ventes, des commandes).
Il ne clique JAMAIS sur « Payer … via Orange Money » : aucun appel à Orange.

Pré-requis (poste de dev) :
  pip install playwright pillow && playwright install chromium
  # base de démo séparée, pour ne pas toucher vos données de dev :
  export DEV_SQLITE_NAME=demo_motion.sqlite3            # (PowerShell : $env:DEV_SQLITE_NAME="demo_motion.sqlite3")
  python manage.py migrate --settings=config.settings.dev
  python manage.py runserver --settings=config.settings.dev      # dans un autre terminal, même variable
  # Ne PAS définir ORANGE_SMS_API_KEY : sinon de vrais SMS partiraient vers les numéros fictifs.
  python motion_capture_demo.py --project-dir . --format both

NB : Celery n'est pas nécessaire (la vente est ouverte à la main avec « Ouvrir la vente »).
Script NON EXÉCUTÉ au moment de sa rédaction : voir « Points de fragilité » dans le dossier.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

TZ = ZoneInfo("Africa/Bamako")

# ── Données fictives (aucune personne ni boutique réelle) ───────────────────────
PASSWORD = "DemoMotion!2026"
SELLERS = {  # un compte par format, pour pouvoir lancer « both » sans collision
    "vertical": {"phone": "+22370000901", "shop": "Boutique Démo Aminata"},
    "horizontal": {"phone": "+22370000902", "shop": "Boutique Démo Moussa"},
}
BUYERS = [  # numéros de test : vérifier qu'ils n'appartiennent à personne avant usage réel
    {"name": "Client Démo Un", "phone": "+22370000101", "addr": "Hamdallaye ACI 2000, près de la pharmacie (démo)"},
    {"name": "Client Démo Deux", "phone": "+22370000102", "addr": "Badalabougou, rue 12 (démo)"},
    {"name": "Client Démo Trois", "phone": "+22370000103", "addr": "Kalaban Coura, derrière l'école (démo)"},
]
QUICK_PRODUCTS = [  # Publication rapide (sans photo)
    {"name": "Pagne wax 6 yards", "price": 7500, "promo": 6000, "stock": 20},
    {"name": "Sac à main rouge", "price": 12000, "promo": 9500, "stock": 8},
    {"name": "Sandales femme", "price": 5000, "promo": None, "stock": 15},
]
CLASSIC_PRODUCT = {"name": "Bracelet perles", "price": 3000, "stock": 12, "unit": "pièce",
                   "description": "Bracelet fait main (produit de démonstration)."}
SALE = {
    "title": "Vente flash Pagnes et Sacs (démo)",
    "description": "Pagnes wax, sacs et sandales à prix flash. Livraison à Bamako. Données fictives.",
    "teasers": "3 pagnes wax\n5 sacs à main\nSandales femme à prix cassé",
    "zone": "Bamako, ACI 2000",
}

PROFILES = {
    "vertical": dict(viewport={"width": 360, "height": 640}, device_scale_factor=3, is_mobile=True, has_touch=True),
    "horizontal": dict(viewport={"width": 1920, "height": 1080}, device_scale_factor=1),
}
BUYER_PROFILE = PROFILES["vertical"]
# Masque la barre django-debug-toolbar si elle est installée en dev.
HIDE_DEBUG_JS = (
    "document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');"
    "s.textContent='#djDebug{display:none!important}';document.head.appendChild(s);});"
)


# ── Utilitaires ─────────────────────────────────────────────────────────────────
class Shooter:
    def __init__(self, out_dir: Path):
        self.out = out_dir
        self.out.mkdir(parents=True, exist_ok=True)
        self.n = 0
        self.items: list[dict] = []
        self.errors: list[dict] = []

    def shot(self, page, who: str, name: str, *, note: str = "") -> None:
        self.n += 1
        fname = f"{self.n:02d}_{who}_{name}.png"
        page.screenshot(path=str(self.out / fname), full_page=False)
        self.items.append({"file": fname, "who": who, "url": page.url, "note": note})
        print(f"  [ok] {fname}")

    @contextmanager
    def step(self, page, label: str):
        try:
            yield
        except Exception as exc:  # on continue : une étape ratée ne doit pas tout arrêter
            self.errors.append({"step": label, "error": str(exc)[:400], "url": page.url})
            print(f"  [ERREUR] {label}: {str(exc)[:160]}")
            try:
                page.screenshot(path=str(self.out / f"ERREUR_{re.sub(r'[^a-z0-9]+', '_', label.lower())}.png"))
            except Exception:
                pass


def settle(page, ms: int = 700) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    try:
        page.evaluate("document.fonts && document.fonts.ready")
    except Exception:
        pass
    page.wait_for_timeout(ms)


def go(page, base: str, path: str) -> None:
    page.goto(base + path, wait_until="load")
    settle(page)


def scroll_series(S: Shooter, page, who: str, name: str, max_shots: int = 6) -> None:
    """Captures successives en descendant la page (évite les très grandes full_page à facteur 3)."""
    h = page.evaluate("window.innerHeight")
    total = page.evaluate("document.documentElement.scrollHeight")
    y, i = 0, 1
    while i <= max_shots:
        page.evaluate(f"window.scrollTo(0,{y})")
        page.wait_for_timeout(500)
        S.shot(page, who, f"{name}_{i}")
        y += int(h * 0.85)
        i += 1
        if y >= total:
            break
    page.evaluate("window.scrollTo(0,0)")


def make_image(path: Path, label: str, color: tuple[int, int, int]) -> None:
    img = Image.new("RGB", (900, 900), color)
    d = ImageDraw.Draw(img)
    font = None
    for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "seguibl.ttf"):
        try:
            font = ImageFont.truetype(name, 64)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    d.text((60, 400), label, fill="white", font=font)
    d.text((60, 800), "DÉMO — image fictive", fill="white", font=font)
    img.save(path)


def set_plan(project_dir: str, phone: str, plan: str, days: int = 31) -> None:
    """Simule le plan sans paiement (même effet que les actions de l'admin Django). LOCAL uniquement."""
    code = (
        "from accounts.models import User\n"
        "from subscriptions.models import Subscription\n"
        "from django.utils import timezone\n"
        "from datetime import timedelta\n"
        f"u = User.objects.get(phone={phone!r})\n"
        "s, _ = Subscription.objects.get_or_create(seller=u.seller_profile)\n"
        f"s.plan = {plan!r}\n"
        f"s.expires_at = None if {plan!r} == 'free' else timezone.now() + timedelta(days={days})\n"
        "s.save()\n"
        "print('plan ->', s.plan, s.expires_at)\n"
    )
    subprocess.run(
        [sys.executable, "manage.py", "shell", "--settings=config.settings.dev", "-c", code],
        cwd=project_dir, check=True,
    )


def new_page(browser, profile: dict):
    ctx = browser.new_context(locale="fr-FR", timezone_id="Africa/Bamako", **profile)
    ctx.add_init_script(HIDE_DEBUG_JS)
    page = ctx.new_page()
    page.on("dialog", lambda d: d.accept())  # confirm() natifs : « Ouvrir la vente maintenant ? » etc.
    return ctx, page


# ── Parcours ────────────────────────────────────────────────────────────────────
def run_format(p, fmt: str, args) -> dict:
    base = args.base_url.rstrip("/")
    demo = SELLERS[fmt]
    out = Path(args.out) / fmt
    S = Shooter(out)
    tmp = out / "_img"
    tmp.mkdir(exist_ok=True)
    cover, bracelet = tmp / "couverture.png", tmp / "bracelet.png"
    make_image(cover, "VENTE FLASH", (230, 57, 70))
    make_image(bracelet, "Bracelet perles", (91, 46, 255))

    browser = p.chromium.launch(headless=not args.headed)
    sctx, sp = new_page(browser, PROFILES[fmt])  # vendeur
    print(f"\n=== Format {fmt} — compte {demo['phone']} ===")

    # 0. Pages publiques (visiteur non connecté)
    with S.step(sp, "accueil"):
        go(sp, base, "/")
        scroll_series(S, sp, "visiteur", "accueil")
    with S.step(sp, "calendrier_vide"):
        go(sp, base, "/ventes/")
        S.shot(sp, "visiteur", "calendrier_ventes_vide")

    # 1. Inscription (ou connexion si le compte existe déjà)
    with S.step(sp, "inscription"):
        go(sp, base, "/register/")
        S.shot(sp, "vendeur", "inscription_vide")
        sp.fill('input[name="business_name"]', demo["shop"])
        sp.fill('input[name="phone"]', demo["phone"])
        sp.fill('input[name="password"]', PASSWORD)
        sp.fill('input[name="password2"]', PASSWORD)
        sp.check("#accept_terms")
        S.shot(sp, "vendeur", "inscription_remplie")
        sp.wait_for_timeout(3500)  # anti-bot : délai minimal de remplissage = 3 s
        sp.get_by_role("button", name=re.compile("Créer mon compte")).click()
        try:
            sp.wait_for_url(re.compile(r".*/seller/?$"), timeout=10000)
        except PWTimeout:
            go(sp, base, "/login/")  # compte déjà créé lors d'un essai précédent
            S.shot(sp, "vendeur", "connexion_vide")
            sp.fill('input[name="phone"]', demo["phone"])
            sp.fill('input[name="password"]', PASSWORD)
            S.shot(sp, "vendeur", "connexion_remplie")
            sp.get_by_role("button", name="Se connecter").click()
            sp.wait_for_url(re.compile(r".*/seller/?$"), timeout=10000)
        settle(sp)
        S.shot(sp, "vendeur", "tableau_de_bord_vide")

    with S.step(sp, "ecrans_vides"):
        go(sp, base, "/seller/flash-sales/")
        S.shot(sp, "vendeur", "mes_ventes_vide")
        go(sp, base, "/seller/abonnement/")
        S.shot(sp, "vendeur", "abonnement_gratuit")
        go(sp, base, "/seller/abonnement/checkout/pro/")
        S.shot(sp, "vendeur", "paiement_pro_orange_money", note="NE PAS cliquer sur Payer")
        go(sp, base, "/seller/flash-sales/analytics/")
        S.shot(sp, "vendeur", "statistiques_verrouillees_gratuit")
        go(sp, base, "/orders/seller/dashboard/")
        S.shot(sp, "vendeur", "commandes_aucune_vente")

    # 2. Création de la vente (démarre dans 10 min pour pouvoir montrer la page d'attente)
    pk = slug = ""
    with S.step(sp, "creation_vente"):
        now = datetime.now(TZ)
        start = now + timedelta(minutes=10)
        if start.date() != now.date():  # évite le passage à minuit (règle « 3 ventes / jour »)
            start = now + timedelta(minutes=2)
        go(sp, base, "/seller/flash-sales/create/")
        S.shot(sp, "vendeur", "creation_vente_vide")
        sp.fill("#id_title", SALE["title"])
        sp.fill('textarea[name="description"]', SALE["description"])
        sp.fill('textarea[name="teasers"]', SALE["teasers"])
        sp.fill('input[name="start_time"]', start.strftime("%Y-%m-%dT%H:%M"))
        sp.select_option('select[name="category"]', "mode")
        sp.fill('input[name="delivery_zone"]', SALE["zone"])
        sp.set_input_files('input[name="cover_image"]', str(cover))
        sp.get_by_text("+ Durée personnalisée").click()
        sp.fill('input[name="custom_duration_minutes"]', "90")
        S.shot(sp, "vendeur", "creation_duree_personnalisee")
        sp.get_by_text("Urgence maximale").click()  # revient à « 1 heure »
        sp.wait_for_timeout(400)
        S.shot(sp, "vendeur", "creation_vente_remplie")
        sp.get_by_role("button", name=re.compile("Programmer la vente")).click()
        sp.wait_for_url(re.compile(r".*/seller/flash-sales/\d+/$"), timeout=15000)
        settle(sp)
        pk = re.search(r"/flash-sales/(\d+)/", sp.url).group(1)
        link = sp.locator("input[readonly]").first.input_value()
        slug = link.rstrip("/").split("/")[-1]
        S.shot(sp, "vendeur", "fiche_vente_sans_produit")

    if not pk:
        browser.close()
        return {"format": fmt, "files": S.items, "errors": S.errors}

    # 3. Publication rapide (3 produits)
    with S.step(sp, "publication_rapide"):
        go(sp, base, f"/seller/flash-sales/{pk}/quick-publish/")
        S.shot(sp, "vendeur", "publication_rapide_vide")
        for prod in QUICK_PRODUCTS:
            sp.get_by_role("button", name="+ Nouveau produit").click()
            row = sp.locator(".qp-row").first  # les nouvelles lignes s'insèrent en tête
            row.locator('input[placeholder="Nom du produit"]').fill(prod["name"])
            row.locator('input[id^="qp-price-"]').fill(str(prod["price"]))
            if prod["promo"]:
                row.locator('input[id^="qp-promo-"]').fill(str(prod["promo"]))
            row.locator('input[id^="qp-stock-"]').fill(str(prod["stock"]))
        sp.wait_for_timeout(500)
        S.shot(sp, "vendeur", "publication_rapide_remplie")
        sp.get_by_role("button", name=re.compile(r"Publier \d+ produit")).click()
        sp.get_by_text(re.compile(r"publié")).first.wait_for(timeout=10000)
        S.shot(sp, "vendeur", "publication_rapide_succes")

    # 4. Ajout produit — méthode classique (avec photo)
    with S.step(sp, "ajout_classique"):
        go(sp, base, f"/seller/flash-sales/{pk}/products/create/")
        S.shot(sp, "vendeur", "ajout_classique_vide")
        sp.set_input_files('input[name="image"]', str(bracelet))
        sp.fill('input[name="name"]', CLASSIC_PRODUCT["name"])
        sp.fill('textarea[name="description"]', CLASSIC_PRODUCT["description"])
        sp.fill('input[name="price"]', str(CLASSIC_PRODUCT["price"]))
        sp.fill('input[name="stock_initial"]', str(CLASSIC_PRODUCT["stock"]))
        sp.fill('input[name="unit"]', CLASSIC_PRODUCT["unit"])
        S.shot(sp, "vendeur", "ajout_classique_rempli")
        sp.get_by_role("button", name="Ajouter le produit").click()
        sp.wait_for_url(re.compile(r".*/seller/flash-sales/\d+/$"), timeout=15000)
        settle(sp)
        S.shot(sp, "vendeur", "fiche_vente_avec_produits")

    # 5. Page publique AVANT l'ouverture (« Bientôt ») + inscription « M'alerter »
    bctx, bp = new_page(browser, BUYER_PROFILE)
    with S.step(bp, "public_attente"):
        go(bp, base, f"/f/{slug}/")
        S.shot(bp, "acheteur", "page_attente_compte_a_rebours")
        bp.locator("#btn-notify-waiting").click()
        bp.wait_for_timeout(900)
        bp.fill("#interest-name-w", "Client Démo Alerte")
        bp.fill("#interest-phone-w", "+22370000199")
        S.shot(bp, "acheteur", "alerter_formulaire")
        bp.locator("#interest-submit-w").click()
        bp.wait_for_timeout(1200)
        S.shot(bp, "acheteur", "alerter_confirmation")
    bctx.close()

    # 6. Ouverture manuelle de la vente (Celery absent en dev)
    with S.step(sp, "ouverture"):
        go(sp, base, f"/seller/flash-sales/{pk}/")
        sp.get_by_role("button", name="Ouvrir la vente").click()
        sp.wait_for_load_state("load")
        settle(sp)
        S.shot(sp, "vendeur", "fiche_vente_en_cours")
        sp.get_by_role("button", name=re.compile("QR Code")).click()
        sp.get_by_text("Scannez pour commander").wait_for(timeout=8000)
        S.shot(sp, "vendeur", "qr_code")
        sp.get_by_role("button", name="Fermer").first.click()
        go(sp, base, "/ventes/")
        S.shot(sp, "vendeur", "calendrier_ventes_en_direct")

    # 7. Trois acheteurs fictifs commandent
    for i, buyer in enumerate(BUYERS):
        bctx, bp = new_page(browser, BUYER_PROFILE)
        with S.step(bp, f"commande_acheteur_{i + 1}"):
            go(bp, base, f"/f/{slug}/")
            if i == 0:
                S.shot(bp, "acheteur", "page_vente_en_direct")
                scroll_series(S, bp, "acheteur", "page_vente_defilement", max_shots=3)
            bp.get_by_role("button", name=re.compile(r"^Commander ·")).nth(i % len(QUICK_PRODUCTS)).click()
            bp.wait_for_timeout(700)
            if i == 0:
                S.shot(bp, "acheteur", "commande_tiroir_vide")
            if i == 1:
                bp.get_by_role("button", name="+", exact=True).click()  # quantité 2
            bp.get_by_placeholder("Ex: Mariam Kone").fill(buyer["name"])
            bp.locator('input[type="tel"]').fill(buyer["phone"])
            bp.get_by_placeholder(re.compile("Quartier")).fill(buyer["addr"])
            if i == 0:
                S.shot(bp, "acheteur", "commande_tiroir_rempli")
            bp.get_by_role("button", name="Confirmer la commande").click()
            bp.get_by_text("Commande envoyée !").wait_for(timeout=15000)
            if i == 0:
                S.shot(bp, "acheteur", "commande_envoyee")
        bctx.close()

    # 8. Suivi des commandes (vendeur)
    with S.step(sp, "suivi_commandes"):
        go(sp, base, "/orders/seller/dashboard/")
        sp.locator('[id^="order-row-"]').first.wait_for(timeout=15000)
        sp.wait_for_timeout(1500)
        S.shot(sp, "vendeur", "commandes_en_direct")
        rows = sp.locator('[id^="order-row-"]')
        oldest = rows.last.get_attribute("id")
        middle = rows.nth(1).get_attribute("id") if rows.count() > 1 else None
        for k in range(3):  # En attente -> Confirmé -> En livraison -> Livré et payé
            sp.locator(f"#{oldest} button").click()
            sp.wait_for_timeout(1300)
            if k == 0:
                S.shot(sp, "vendeur", "commande_confirmee")
        if middle:
            sp.locator(f"#{middle} button").click()  # reste « Confirmé » pour l'écran Livraisons
            sp.wait_for_timeout(1300)
        sp.wait_for_timeout(4500)  # cache des KPI : 4 s
        S.shot(sp, "vendeur", "commandes_apres_avancement")

    # 9. Livraisons
    with S.step(sp, "livraisons"):
        go(sp, base, f"/orders/seller/deliveries/?flash_sale_id={pk}")
        sp.locator('[id^="delivery-row-"]').first.wait_for(timeout=15000)
        sp.wait_for_timeout(1200)
        S.shot(sp, "vendeur", "livraisons_liste")
        row = sp.locator('[id^="delivery-row-"]:has(input[name="assigned_to"])').first
        row.locator('input[name="assigned_to"]').fill("Moussa (livreur démo)")
        S.shot(sp, "vendeur", "livraisons_nom_livreur")
        row.get_by_role("button", name="En livraison").click()  # POST classique : peut afficher un fragment (à vérifier)
        sp.wait_for_timeout(1500)
        go(sp, base, f"/orders/seller/deliveries/?flash_sale_id={pk}")
        S.shot(sp, "vendeur", "livraisons_apres_action")

    # 10. Fermeture de la vente + page publique « terminée »
    with S.step(sp, "fermeture"):
        go(sp, base, f"/seller/flash-sales/{pk}/")
        sp.get_by_role("button", name="Fermer la vente").click()
        sp.wait_for_load_state("load")
        settle(sp)
        S.shot(sp, "vendeur", "fiche_vente_fermee")
    bctx, bp = new_page(browser, BUYER_PROFILE)
    with S.step(bp, "public_terminee"):
        go(bp, base, f"/f/{slug}/")
        S.shot(bp, "acheteur", "page_vente_terminee")
    bctx.close()

    # 11. Plans : Gratuit (déjà vu) -> Medium -> Pro
    for plan in ("medium", "pro"):
        with S.step(sp, f"plan_{plan}"):
            set_plan(args.project_dir, demo["phone"], plan)
            go(sp, base, "/seller/abonnement/")
            S.shot(sp, "vendeur", f"abonnement_{plan}")
            go(sp, base, "/seller/flash-sales/analytics/")
            sp.wait_for_timeout(1800)  # animation des graphiques
            S.shot(sp, "vendeur", f"statistiques_{plan}")

    # 12. Autres écrans vendeur
    with S.step(sp, "autres_ecrans"):
        go(sp, base, "/seller/")
        S.shot(sp, "vendeur", "tableau_de_bord_avec_ventes")
        go(sp, base, "/seller/flash-sales/")
        S.shot(sp, "vendeur", "mes_ventes_liste")
        go(sp, base, "/seller/profil/")
        S.shot(sp, "vendeur", "profil")
        go(sp, base, "/seller/parametres/")
        S.shot(sp, "vendeur", "parametres")
        go(sp, base, "/seller/flash-sales/interests/")
        S.shot(sp, "vendeur", "reservations")

    manifest = {
        "format": fmt, "base_url": base, "generated": datetime.now(TZ).isoformat(timespec="seconds"),
        "viewport": PROFILES[fmt], "fictional_data": True, "files": S.items, "errors": S.errors,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    browser.close()
    print(f"-> {len(S.items)} captures, {len(S.errors)} erreur(s). Dossier : {out}")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--project-dir", default=".", help="dossier contenant manage.py")
    ap.add_argument("--out", default="motion_assets")
    ap.add_argument("--format", choices=["vertical", "horizontal", "both"], default="vertical")
    ap.add_argument("--headed", action="store_true", help="afficher le navigateur")
    args = ap.parse_args()

    host = urlparse(args.base_url).hostname
    if host not in ("127.0.0.1", "localhost"):
        sys.exit("Refusé : ce script ne doit tourner que contre un serveur LOCAL (127.0.0.1 / localhost).")
    if not (Path(args.project_dir) / "manage.py").exists():
        sys.exit("manage.py introuvable : indiquez --project-dir.")
    if os.environ.get("ORANGE_SMS_API_KEY"):
        sys.exit("ORANGE_SMS_API_KEY est définie : retirez-la, des SMS réels partiraient vers les numéros fictifs.")

    formats = ["vertical", "horizontal"] if args.format == "both" else [args.format]
    with sync_playwright() as p:
        for fmt in formats:
            run_format(p, fmt, args)


if __name__ == "__main__":
    main()
```

---

## 7. Acquis existants (vidéo / marketing)

**Non trouvé** : pipeline TikTok, scripts vidéo, outils de montage (ffmpeg, remotion…), fichiers vidéo ou animés (mp4, mov, webm, gif), et le mot « Hormozi » (absent de tout le dépôt).

TikTok n'apparaît que dans : `templates/core/home.html` (texte), la fenêtre QR (« Idéal pour vos lives TikTok / Facebook »), `static/js/hf-install.js` (détection du navigateur intégré), l'aide du champ vidéo d'un produit (`products/models.py:116`) et `docs/ANALYSE_V1_LAUNCH.md`.

**Trouvé, réutilisable comme base** :
- Captures `static/img/screenshots/seller-desktop.png` et `seller-mobile.png` (23/09).
- Dossier `Claude outputs/` : `22_client_order_after_submit.png`, `23_platform_admin.png` (écran réservé au personnel : ne pas montrer), `audit_playwright.py` (script d'audit avec chemins en dur type `/root/work/audit_output`, utilisable comme base), notes sur la publication rapide.
- `docs/releases/reports/ui-home-apercu-avant.html` / `-apres.html` (non suivis par git), `ui-icones-apercu.html`, `ui-icones-proposition.md`.
- Textes de la page d'accueil (§5) : seul matériel de « ton » existant.

---

## 8. Écarts — promesses ≠ application

| Réf. | Écart | Source |
|------|-------|--------|
| E-01 | Page Statistiques sans lien de menu ; un vendeur Pro n'a aucun lien vers l'Abonnement. | `flash_sales/urls.py:9` |
| E-02 | Aucune annulation de commande (vendeur ni acheteur), malgré « confirmez ou annulez en un tap » et « Annulation possible avant livraison ». | `home.html:451`, `flash_sale_public.html:605` |
| E-03 | « Plafond de commandes » enregistré et affiché mais jamais appliqué. | `flash_sales/models.py:74` |
| E-04 | Livraisons : boutons « Livrée » / « Échec » jamais affichés (`can_complete`/`can_fail` testés, `can_mark_delivered`/`can_mark_failed` fournis) et noms d'actions différents ; « En livraison » en formulaire classique pouvant afficher un fragment. | `delivery_row.html:108,122` ; `seller_dashboard.py:163,165` ; `delivery/views.py:209-217` |
| E-05 | Confirmation/livraison en masse : routes présentes, aucune interface. | `orders/` urls |
| E-06 | « Livraisons groupées automatiquement », « taux de livraison », « clients fidèles », « meilleurs horaires », « CA par vente flash » : non trouvés. | `home.html`, `analytics_upgrade.html` |
| E-07 | Annoncés Pro mais non bloqués ou sans code : tableau LIVE, SMS (dépend d'une clé SMS), support WhatsApp prioritaire, avant-première ; « Historique des commandes complet » (Medium) alors que 20 commandes max pour tous. | `subscriptions` PlanConfig ; `orders/services/dashboard.py` |
| E-08 | **Libellés incohérents** : « Gratuit » / « Free » · « MEDIUM ou PRO » / « Medium/Pro » · « Passer au PRO » / « Passer Pro » / « Choisir Pro » / « Passer a Pro » · « Recommande » sans accent, sur Pro (liste, fenêtre, abonnement) mais sur Medium (`quota_exceeded`) · menu « Mes ventes » (→ tableau de bord) ≠ page « Mes ventes flash » · « Dashboard LIVE » / « Tableau LIVE » / « Dashboard » · « Programmer une vente flash » / « Nouvelle vente » / « Créer une vente » · « Réservations » (vendeur) / « M'alerter » (acheteur) · onglet « Traitement » / badge « Fermée » · « Livré et payé » / « Livré » / « Livrée » · filtre « Annulées » ≠ badge « Échec livraison » · jargon « COD », « CA » · accents manquants (« Precisez la duree », « Paiement a la livraison », « Vente clonee ») · mot de passe 6 (inscription) / 8 (paramètres) · « 30 secondes » / « 60 secondes » · marque réelle « Gucci » dans un exemple de titre. **« Premium » : non trouvé.** | divers |
| E-09 | « {vendeur} vous appellera » : aucun mécanisme dans l'app (seulement SMS de rappel si configuré, et alerte du navigateur). | page publique |
| E-10 | Bio « visible publiquement » (politique de confidentialité) mais non affichée. | `privacy` / pages publiques |
| E-11 | Cartes « Ventes actives / terminées » plafonnées à 5 et 3. | `seller/home.html` |
| E-12 | Plan expiré toujours affiché sous son ancien nom, sans date. | `subscription.html:23` |
| E-13 | « Non vérifié » affiché à tous (code SMS inactif). | `settings.html` |
| E-14 | Messages d'erreur acheteur encore en anglais sur cette branche (F-66 corrigé ailleurs). | `orders/services/client_order.py:71,73,112,137,145,147,152` |
| E-15 | Témoignages et chiffres de l'accueil sans source. | `home.html` |
| E-16 | Déploiement du VPS en pause ; release rc1 en préparation → les vidéos ne doivent pas annoncer une date de mise en ligne. | `CLAUDE.md`, `docs/releases/` |
| E-17 | Fragilités connues : planificateur (F-20), stock sans expiration (F-59), spam possible sur « M'alerter » (F-60), lien manquant sur la page EN DIRECT (F-64). | registre rc1 |
| E-18 | « Dicter en bambara, français, wolof » : c'est un **enregistrement audio**, pas une transcription. « Écouter » lit le texte écrit en voix française. | `create.html` |
| E-19 | `CLAUDE.md` donne la couleur #E63946 ; le code utilise #FF4D2E. | `CLAUDE.md` vs `docs/FRONTEND_VENDORING.md` |

Références du registre déjà existantes : F-17, F-20, F-23, F-36, F-59, F-60, F-64, F-66.
