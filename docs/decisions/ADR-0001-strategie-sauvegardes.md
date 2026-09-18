# ADR-0001 — Stratégie de sauvegarde (DB + médias)

- **Statut** : Acceptée
- **Date** : 2026-09-18
- **Contexte projet** : HayaFlash — catégorie 5 (Sauvegardes & reprise après sinistre) de `GOVERNANCE_SECURITE.md`, identifiée comme la plus en retard du projet.
- **Lié à** : PR [#18](https://github.com/SamK107/hayaflash/pull/18) (`infra/scripts/backup.sh`, `infra/scripts/restore_test.sh`), testés en local via simulateur Docker, aucun accès prod.

## Contexte

Le projet n'a aucune sauvegarde automatisée à ce jour : ni dump PostgreSQL, ni copie des médias, ni chiffrement, ni copie hors-site, ni test de restauration (voir `GOVERNANCE_SECURITE.md`, section 5). Les scripts `backup.sh` (dump DB + archive médias, rétention locale) et `restore_test.sh` (restauration + comptage de tables) existent et sont validés en local, mais quatre décisions d'infrastructure restaient ouvertes avant toute mise en production : lieu de stockage hors-site, chiffrement, activation du cron VPS, et première exécution réelle.

Ces décisions doivent être prises maintenant — pour que les scripts soient écrits dans la bonne architecture dès le départ — mais **appliquées seulement à la fin**, une fois la gouvernance, la sécurité et le SEO du projet finalisés, conformément au séquencement de déploiement retenu pour tous les projets (gouvernance → durcissement sécurité/SEO → déploiement VPS).

## Décision

**1. Stockage hors-site : disque externe, pas de stockage cloud.**
Le stockage de la copie hors-site sera un disque externe branché périodiquement sur le VPS, sur le même principe que celui déjà en place pour services.symain.africa. Pas de S3, Backblaze ou équivalent à ce stade.
Conséquence pour le script : la copie vers le disque externe doit être une étape séparée du dump principal, défensive et idempotente — elle détecte la présence du point de montage (ex. `/mnt/backup-ext`), copie si présent, ne rejoue pas ce qui a déjà été copié, et logue proprement sans échec bloquant si le disque est absent. Le dump + rétention locale sur le VPS tourne indépendamment de la présence du disque.

**2. Chiffrement : obligatoire pour tout ce qui sort du VPS.**
Tout backup écrit sur le disque externe doit être chiffré au repos avant écriture (age ou gpg symétrique, passphrase forte). La clé/passphrase ne réside ni sur le VPS ni sur le disque externe — gestionnaire de mots de passe uniquement. Un disque externe transportable est un vecteur de perte/vol plus probable qu'une fuite serveur ; ce n'est pas négociable. Les dumps qui restent en local sur le VPS le temps de la rétention courte peuvent rester non chiffrés (protégés par les accès du serveur lui-même).

**3. Cron VPS : reporté à la phase de déploiement.**
Le cron d'exécution automatique sur le VPS n'est pas activé maintenant. Il sera mis en place à la toute fin, une fois les fichiers de gouvernance finalisés, les branches mergées, et les améliorations de sécurité/SEO en place — dans le cadre du déploiement complet du projet, pas comme une étape isolée. Le script doit cependant être cron-ready dès maintenant (non-interactif, codes de sortie propres, logs exploitables) : c'est déjà le cas d'après les tests locaux.

**4. Première exécution réelle : intégrée à la checklist de déploiement final.**
Pas d'exécution isolée sur le VPS avant que le reste du projet soit prêt. Lors du déploiement final : exécuter `backup.sh` une première fois en conditions réelles, puis valider immédiatement avec `restore_test.sh` sur ce dump réel (pas seulement sur les simulateurs utilisés en dev). C'est ce test de restauration réelle qui conditionne la mise en confiance dans la stratégie, pas la simple exécution du dump.

## Conséquences

- Les scripts déjà écrits et testés (PR #18) restent valables tels quels pour la partie dump/rétention/restauration ; ils doivent être complétés par l'étape de copie chiffrée vers le disque externe avant d'être considérés terminés.
- Aucune action n'est prise sur le VPS avant la fin du projet — cette ADR documente l'intention, pas une exécution.
- `GOVERNANCE_SECURITE.md` section 5 reste à ❌ jusqu'à la mise en œuvre effective de ces décisions ; seule leur documentation change de statut aujourd'hui (de "non décidé" à "décidé, en attente d'exécution").
- Limite reconnue : un disque externe branché au même endroit physique que le VPS ne respecte pas pleinement la règle 3-2-1 (pas de véritable copie géographiquement séparée en cas de sinistre sur site). Accepté comme compromis pragmatique à ce stade ; à réévaluer si le projet passe en usage critique/production à fort enjeu.

## Alternatives envisagées

- **Stockage cloud objet (S3/Backblaze B2)** : écarté pour l'instant — coût récurrent et dépendance externe non retenus à ce stade du projet ; cohérent avec le choix déjà fait sur services.symain.africa.
- **Cron actif dès maintenant** : écarté — activer une automatisation sur un VPS qui n'a pas encore reçu le durcissement sécurité prévu (catégorie 7 de `GOVERNANCE_SECURITE.md`) créerait une fausse impression de préparation.
