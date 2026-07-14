# HayaFlash — Plan Démo & Comptes de Test

> Document de référence pour les comptes de démonstration, la simulation d'abonnements,
> et la stratégie de données de test.
> Créé le 2026-07-14.

---

## 1. Pourquoi des comptes de démo ?

Les meilleures SaaS (Linear, Notion, Crisp, Shopify dev stores) proposent des
environnements pré-peuplés pour trois raisons :

| Besoin | Bénéfice |
|--------|----------|
| **Tests visuels par plan** | Voir ce que voit un abonné FREE / MEDIUM / PRO sans bidouiller |
| **Démonstration partenaires** | Montrer un dashboard vivant en 30 secondes |
| **Onboarding équipe** | Nouveau développeur → données réelles disponibles immédiatement |
| **Tests de régression** | Comparer l'apparence avant/après un chantier |

---

## 2. Les quatre boutiques de démo

| Boutique | Téléphone | Mot de passe | Plan | Catégorie |
|----------|-----------|--------------|------|-----------|
| **ALPHA CHAUSSURES** | +22371111111 | `Rama123@` | FREE | Chaussures |
| **LES PLATS DU JOUR** | +22372222222 | `Rama123@` | MEDIUM | Cuisine / Food |
| **MONTRE HOMME & FEMME** | +22379999999 | `Rama123@` | PRO | Montres |
| **LUXES & ELEGANCES** | +22300000004 | `Rama123@` | PRO | Mode / Habit |

### Ce que contient chaque boutique

**ALPHA CHAUSSURES (FREE)**
- 3 produits (baskets, chaussure homme, sandales) · photos ch1–ch3.jpg
- 3 ventes flash (1 passée, 1 en cours, 1 programmée)
- ~10 commandes par vente avec statuts variés
- Montre les limites du plan FREE (3 ventes/mois, pas de stats avancées)

**LES PLATS DU JOUR (MEDIUM)**
- 4 produits (thiéboudiène, yassa, sauce arachide, riz gras) · photos p1–p3 + P4.jpg
- 4 ventes flash (turnover quotidien réaliste)
- ~12 commandes par vente
- Accès aux statistiques 30 jours, historique complet

**MONTRE HOMME & FEMME (PRO)**
- 4 produits (G-Shock, montre femme, chronographe, connectée) · photos m1 + M2–M4.jpg
- 4 ventes flash (stock limité réaliste)
- ~14 commandes par vente
- Dashboard complet : stats annuelles, analytics avancées, tout débloqué

**LUXES & ELEGANCES (PRO)**
- 5 produits (boubou, robe soirée, costume, tailleur, kaftan) · photos h1–h5.jpg
- 4 ventes flash (collections mode haut de gamme)
- ~12 commandes par vente
- Vitrine mode africaine premium, idéale pour présenter le dashboard PRO

---

## 3. Commande seed

```bash
# Tout créer (skip si déjà présent)
python manage.py seed_demo --settings=config.settings.dev

# Tout supprimer et recréer proprement
python manage.py seed_demo --reset --settings=config.settings.dev

# Une seule boutique
python manage.py seed_demo --shop chaussures --settings=config.settings.dev
python manage.py seed_demo --shop cuisine --settings=config.settings.dev
python manage.py seed_demo --shop montres --settings=config.settings.dev
python manage.py seed_demo --shop habit --settings=config.settings.dev
```

### Photos produits attendues

Les images sont déjà injectées automatiquement via `ProductMedia` lors du seed.
Structure attendue dans `static/img/demo/` :

```
static/img/demo/
  chaussures/
    ch1.jpg   ← Basket sport blanche
    ch2.jpg   ← Chaussure habillée homme
    ch3.jpg   ← Sandale femme colorée
  cuisine/
    p1.jpg    ← Thiéboudiène poisson
    p2.jpg    ← Poulet yassa riz
    p3.jpg    ← Sauce arachide + foutou
    P4.jpg    ← Riz gras mouton  (attention : P majuscule)
  montres/
    m1.jpg    ← Casio G-Shock DW-5600
    M2.jpg    ← Montre Femme Dorée  (M majuscule)
    M3.jpg    ← Chronographe Homme  (M majuscule)
    M4.jpg    ← Montre Connectée   (M majuscule)
  habit/
    h1.jpg    ← Boubou Grand Bassam brodé
    h2.jpg    ← Robe de soirée en pagne
    h3.jpg    ← Costume 3 pièces homme
    h4.jpg    ← Ensemble pagne tailleur femme
    h5.jpg    ← Kaftan brodé or & argent
```

Si un fichier est absent → le produit est créé sans photo (aucun crash).

---

## 4. Simulation d'abonnement (admin)

Sans attendre un paiement Orange Money, depuis l'admin Django :

### Via la liste Abonnements (`/admin/subscriptions/subscription/`)
1. Cocher un ou plusieurs abonnements
2. Dérouler "Action"
3. Choisir :
   - **🔧 Simuler plan Gratuit (perpétuel)**
   - **🔧 Simuler plan Medium (90 jours)**
   - **🔧 Simuler plan Pro (90 jours)**
4. Cliquer "Appliquer"

### Via la liste Vendeurs (`/admin/accounts/sellerprofile/`)
Même principe : les mêmes actions sont disponibles depuis la liste des `SellerProfile`.
Pratique pour changer le plan d'un vendeur sans chercher son abonnement.

### Modifier directement le plan
Dans la vue détail d'un abonnement, les champs `plan` et `expires_at` sont éditables.

---

## 5. Bonnes pratiques démo (standards SaaS)

| Pratique | HayaFlash |
|----------|-----------|
| Données réalistes (vrais produits, vrais prix CFA) | ✅ fait |
| Statuts de commandes variés (pending / delivered / cancelled) | ✅ fait |
| Plans différents pour chaque boutique | ✅ fait |
| Commande idempotente (skip si déjà présent) | ✅ `--reset` pour recréer |
| Isolation (numéros réservés +2237 1/2/9 xxx) | ✅ fait |
| Flag `is_demo` sur SellerProfile | 🔲 à ajouter si reset automatisé nécessaire |
| Reset périodique (cron hebdo) | 🔲 à planifier quand VPS disponible |
| Badge "DÉMO" visible dans l'UI | 🔲 optionnel — utile pour les showroom partenaires |

---

## 6. Étapes à faire après réception des photos

- [ ] Déposer les images dans `static/img/demo/<categorie>/`
- [ ] Décommenter le bloc injection photos dans `seed_demo.py`
- [ ] Lancer `python manage.py seed_demo --reset`
- [ ] Vérifier les pages publiques `/f/<slug>/` et `/s/<slug>/`
- [ ] Vérifier le dashboard de chaque boutique par plan

---

## 7. Évolutions futures (post-MVP)

- **Reset automatisé** : cron `seed_demo --reset` chaque lundi (évite la dégradation des données)
- **Page showroom publique** : `/demo/` listant les 3 boutiques avec un badge DÉMO
- **Mode lecture seule** : les comptes démo ne peuvent pas envoyer de vrais SMS/WhatsApp
- **Génération de données IA** : noms, adresses, commentaires générés pour plus de réalisme
