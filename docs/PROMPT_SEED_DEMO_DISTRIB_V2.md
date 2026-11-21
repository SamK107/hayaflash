# PROMPT — Étendre `seed_demo_distrib` (données démo pour les vidéos grossistes)

## Contexte
Repo : `C:\projets\hayaflash`. La commande `distrib/management/commands/seed_demo_distrib.py` crée déjà un jeu de démonstration Distrib : grossiste **Seydou Maïga (+22370000001, « Grossiste Démo Bamako »)**, 5 revendeuses (+22370000011 à 15), 5 boutiques Marché (+22370000021 à 25), des clientes (+22370000030 à 44), un admin (+22370000099).

Les vidéos de la campagne grossistes doivent montrer un tableau de bord grossiste **crédible et contrasté** : au moins 15 revendeuses, environ 90 jours d'historique, des écarts nets de performance entre elles.

## Objectif
Étendre le seed existant (pas de nouveau script) pour obtenir, dans le compte de Seydou Maïga :
- **15 revendeuses** au total : garder les 5 existantes et en ajouter 10, sur les numéros **+22370000050 à +22370000059** ;
- de nouvelles clientes sur **+22370000060 à +22370000098** si besoin ;
- un historique réparti sur **90 jours glissants**, relatif à « maintenant » ;
- un catalogue grossiste d'environ 20 produits répartis en habits, chaussures, sacs, parfums et cosmétiques (ex. robe en dentelle, robe longue à foulard, mocassins en cuir, escarpins, abaya, boubou, sac à main, parfum, lait corporel…) ; réutiliser les images de `demo_assets` existantes.

## Profils de revendeuses à simuler
Les écarts doivent se lire tout de suite à l'écran :

| Profil | Nombre | Comportement sur 90 jours |
| --- | --- | --- |
| Star | 2 | 60 à 90 ventes confirmées, presque aucun échec, relevés payés et acceptés |
| Régulière | 5 | 25 à 45 ventes, quelques « pas livré », relevés payés |
| Moyenne | 4 | 10 à 20 ventes, retours de stock (reprise par le grossiste) |
| Irrégulière | 2 | Ventes faibles, taux de « pas livré » élevé → doit déclencher l'alerte de fiabilité sur 30 jours |
| Nouvelle | 2 | Inscrite depuis moins de 3 semaines, 2 à 6 ventes |

Prénoms maliens crédibles (Adja, Oumou, etc. ; éviter les doublons avec les comptes existants), villes variées : Bamako (plusieurs quartiers), Ségou, Sikasso, Kayes, Koutiala.

## À inclure dans l'historique
- Stock alloué par revendeuse et par produit, ventes, et **reprises d'invendus** (`take_back`) pour quelques-unes.
- Commandes à tous les statuts : livrées et payées confirmées (avec un mélange de confirmation par code cliente et de confirmation automatique), en livraison, à confirmer, « pas livré ».
- **Relevés hebdomadaires** sur toute la période : la plupart payés avec une référence Orange Money fictive et acceptés, un ou deux déclarés en attente, un contesté.
- **Un cas d'alerte de prix minimum** : un produit importé dont le prix boutique est passé sous le minimum (pour la capture de la vidéo 2).
- Le **CA du mois en cours** doit être significatif : au moins 30 % de l'activité tombe dans les 30 derniers jours.
- Au moins **une vente flash en cours** au moment du seed, comme aujourd'hui.

## Contraintes impératives
1. **Local uniquement** : garder les garde-fous existants (refus hors DEBUG, staging, prod ou base distante).
2. **Aucune modification** de modèle, de migration ou de code applicatif : tout passe par les services existants (`create_order`, `advance_delivery`, `import_product`, `confirm_paid`, relevés, versements…), comme le seed actuel. Pour antidater, réutiliser le mécanisme déjà présent (`advance_and_date`, etc.).
3. Tous les numéros restent dans la plage démo `^\+223700000\d{2}$` ; `--reset` ne supprime que ces comptes.
4. **Reproductible** : `random.Random(<graine fixe>)`, mêmes données à chaque `--reset`.
5. Montants en **FCFA entiers**, jamais de centimes ; prix de revente au moins égal au prix minimum, sauf le cas d'alerte volontaire.
6. Ne pas casser le jeu de démo actuel : les 5 revendeuses et les 5 boutiques Marché existantes gardent leur rôle.
7. Ne rien déployer. Travailler sur une branche `feat/seed-demo-distrib-v2`, commits clairs.

## Tests et vérification
- Mettre à jour `distrib/tests_seed_demo.py` : nombre de revendeuses, plage de numéros, au moins une alerte de fiabilité, au moins une alerte de prix minimum, au moins un relevé contesté, reproductibilité (deux exécutions → mêmes totaux).
- Lancer : `python manage.py seed_demo_distrib --settings=config.settings.dev --reset`, deux fois de suite, sans erreur.
- Rapport final (le `print_report` existant, enrichi) : par revendeuse, ventes confirmées, CA, stock restant, taux de « pas livré », dû ; puis le CA du mois et le nombre de relevés par statut.
- Lister les URL locales à capturer pour les vidéos : tableau de bord grossiste, liste des revendeuses, stock par produit, relevés (dont un contesté), catalogue avec prix minimum et alerte, page de confirmation cliente avec code à 4 chiffres.

## Hors périmètre
La page « Statistiques par période » (comparaison mois par mois, classement des produits par recettes) n'est **pas** dans ce prompt : elle fera l'objet d'une spécification séparée.
