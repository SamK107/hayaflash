# Sauvegardes HayaFlash

> Créé le 2026-10-17 (PP-06). Scripts : `infra/scripts/backup.sh`, `restore_test.sh`,
> `restore.sh`, `windows/pull_backups.ps1`. Rien ici ne s'exécute tout seul : les
> commandes VPS sont jouées par le porteur du projet.

## 1. Ce qui est sauvegardé

| Quoi | Comment | Fichier |
|---|---|---|
| Base PostgreSQL de la pile | `pg_dump -Fc` via `docker compose exec -T db` (identifiants lus dans le conteneur, jamais affichés) | `db.dump` |
| Médias (images produits, avatars, audios) | `tar czf` du dossier `/app/media` du conteneur `web` (volume `media_data`) | `media.tar.gz` |
| Métadonnées (projet, date UTC, commit, tailles — aucun secret) | écrit par le script | `backup.info` |
| Empreintes | `sha256sum` des trois fichiers | `SHA256SUMS` |

**Non sauvegardé** : le `.env` (contient les secrets — à conserver séparément, hors dépôt),
Redis (cache et file Celery, reconstructibles), les fichiers statiques (régénérés par `collectstatic`),
la configuration Nginx / HestiaCP.

## 2. Où et combien de temps

- **Sur le VPS** : `/srv/backups/<projet>/AAAA-MM-JJ_HHMM/` (heure **UTC**), dossiers `700`,
  fichiers `600`. Prod : `/srv/backups/hayaflash-prod/`.
- **Écriture atomique** : tout est écrit dans `.tmp-…` puis renommé ; une sauvegarde partielle
  n'apparaît jamais sous son nom définitif. Journal : `/srv/backups/<projet>/backup.log`
  (une ligne `OK` ou `FAIL` horodatée par exécution).
- **Rétention VPS** (configurable : `BACKUP_KEEP_DAILY`, `BACKUP_KEEP_WEEKLY`) :
  la dernière sauvegarde de chacun des **14 derniers jours** + la dernière de chacun des
  **8 derniers dimanches**. La plus récente n'est jamais supprimée ; rien n'est purgé si la
  sauvegarde du jour échoue. Seuls les dossiers `AAAA-MM-JJ_HHMM` contenant `SHA256SUMS`
  sont candidats.
- **Sur le PC (disque D:)** : voir § 5 — 30 quotidiennes + 12 mensuelles.

Une sauvegarde est aussi prise **avant chaque déploiement** (`deploy_vps.sh`) et avant chaque
restauration (`restore.sh`).

## 3. Lancer, planifier

```bash
# Essai à blanc (n'écrit rien, ne supprime rien)
bash /srv/hayaflash-prod/infra/scripts/backup.sh /srv/hayaflash-prod --dry-run
# Sauvegarde réelle
bash /srv/hayaflash-prod/infra/scripts/backup.sh /srv/hayaflash-prod
```

Prérequis (une fois) : `sudo install -d -o sam -m 700 /srv/backups /srv/backups/hayaflash-prod`.

**Planification** (utilisateur `sam`, prod seulement, 03:17 UTC) — installation sans écraser la
crontab existante :

```bash
( crontab -l 2>/dev/null | grep -v '# hayaflash-prod-backup' ; \
  echo "17 3 * * * cd /srv/hayaflash-prod && bash infra/scripts/backup.sh /srv/hayaflash-prod >> /srv/backups/hayaflash-prod/cron.log 2>&1 # hayaflash-prod-backup" ) | crontab -
crontab -l
```

Surveillance : `tail -n 5 /srv/backups/hayaflash-prod/backup.log` doit montrer un `OK` de moins
de 24 h. (Une alerte automatique — heartbeat externe — reste à décider.)

## 4. Copie hors du VPS — état et options

**Décision du porteur (17/10/2026)** : la copie hors VPS est un **disque externe D: sur son PC
Windows**, tirée depuis le PC (§ 5). `BACKUP_REMOTE` reste **vide** côté VPS : `backup.sh`
affiche alors « sauvegarde locale uniquement — non protégée contre la perte du VPS » (c'est
voulu ; l'avertissement ne disparaît que si `BACKUP_REMOTE` est renseigné).

Limite assumée : le disque D: n'est à jour que les jours où le PC est allumé et le disque branché ;
c'est une copie **hors site seulement si le PC et le disque ne sont pas au même endroit que le VPS**
(le VPS est chez LWS, donc oui), mais ce n'est **pas** 3-2-1 complet (deux supports, une copie
distante) tant qu'il n'y en a pas une troisième. Options possibles pour la renforcer plus tard
(le choix du fournisseur appartient au porteur ; `rclone` est déjà géré par `backup.sh`) :

| Option | Avantages | Inconvénients |
|---|---|---|
| Stockage objet S3-compatible (Backblaze B2, Wasabi, Scaleway…) via `rclone` | Automatique chaque nuit, indépendant du PC, versionnable | Coût mensuel, compte et clés à gérer ; chiffrer côté client (`rclone crypt`) |
| Second VPS / serveur personnel via `rclone sftp` ou `rsync` | Contrôle total, coût faible | Un autre serveur à maintenir et surveiller |
| Cloud personnel (Google Drive, OneDrive) via `rclone` | Gratuit ou déjà payé | Quotas, jeton OAuth qui expire, données personnelles chez un tiers (chiffrer) |

Les sauvegardes contiennent des données personnelles (numéros de téléphone, adresses) : toute
copie hors VPS doit être **chiffrée** ou rester sur un support que vous contrôlez.

## 5. Copie chiffrée vers le disque D: du PC Windows

`infra/scripts/windows/pull_backups.ps1` (PowerShell 5.1+, OpenSSH Windows intégré, `tar.exe`
de Windows 10+, et **`age`**) tire depuis le VPS les sauvegardes absentes de D:, les **chiffre**
et ne laisse **aucune copie en clair** sur D: :

1. vérifie que `age.exe` est installé (`winget install FiloSottile.age`) et que `D:` est présent
   et inscriptible (sinon message clair, code de sortie 1) ; refuse un dossier de travail situé
   sur D: ;
2. liste les dossiers distants et copie chacun **par `scp`** dans un dossier temporaire du
   **disque système** (`%LOCALAPPDATA%\HayaFlash\tmp-backups`) ;
3. vérifie les SHA256 d'après `SHA256SUMS` ;
4. crée une archive `tar`, la chiffre avec `age` (destinataire = **clé publique** `age1…`) et
   l'écrit sur D: sous `.tmp-<nom>.tar.age`, puis la renomme en `<nom>.tar.age` : jamais de
   sauvegarde partielle visible ;
5. supprime les fichiers en clair du dossier temporaire, succès ou échec ;
6. rétention locale : **30 quotidiennes + 12 mensuelles** (`-GardeQuotidiennes`,
   `-GardeMensuelles`) ; **aucune suppression si une copie a échoué** ;
7. journal `D:\Sauvegardes\HayaFlash\pull.log` ; alerte jaune bien visible (et code de sortie 3)
   si la dernière sauvegarde locale a **plus de 48 h**.

Les sauvegardes du **VPS restent en clair** sur le VPS (`restore_test.sh` en a besoin).
Résultat sur D: : `D:\Sauvegardes\HayaFlash\<projet>\AAAA-MM-JJ_HHMM.tar.age`.

Codes de sortie : `0` ok · `1` disque absent / non inscriptible / `age`, `tar`, clé SSH ou
destinataire manquant · `2` échec de copie, de vérification ou de chiffrement · `3` terminé mais
dernière sauvegarde trop ancienne.

### 5.0 Créer la paire de clés `age` (une fois) — à ne pas rater

```powershell
winget install FiloSottile.age
# Crée la paire ; la clé PRIVÉE est écrite dans le fichier, la clé PUBLIQUE est affichée
age-keygen -o "$env:USERPROFILE\hayaflash-age-PRIVEE.txt"
# Affiche : « Public key: age1... »  → c'est le destinataire à passer au script
```

* **Clé publique (`age1…`)** : sans danger, c'est elle que le script utilise. La noter dans
  la variable d'environnement `HAYAFLASH_AGE_RECIPIENT` ou la passer avec `-CleAge`.
* **Clé privée (fichier `hayaflash-age-PRIVEE.txt`)** : elle seule déchiffre. **Sans elle, les
  sauvegardes sont illisibles, pour toujours.** Dès la création :
  1. la copier sur une **clé USB séparée** (rangée ailleurs que le PC et le disque D:) ;
  2. en garder une **copie papier** (imprimer le fichier) ou la ranger dans un **gestionnaire de
     mots de passe** ;
  3. **supprimer le fichier du PC** (ou le déplacer sur la clé USB) : un PC volé avec la clé
     privée et le disque D: donnerait accès aux sauvegardes ;
  4. vérifier tout de suite avec `decrypt_backup.ps1` (§ 7.1) que la clé stockée déchiffre.

### 5.1 Créer la clé SSH dédiée (une fois)

Sur le PC, dans PowerShell :

```powershell
# Clé ed25519 SANS mot de passe (-N ""), utilisée uniquement pour ce transfert
ssh-keygen -t ed25519 -N '""' -C "hayaflash-backup-pull" -f "$env:USERPROFILE\.ssh\hayaflash_backup_ed25519"
```

Ajouter la clé **publique** dans `~/.ssh/authorized_keys` de `sam` sur le VPS, avec des options qui
retirent les fonctions inutiles (pas de redirection de port, d'agent, d'X11 ni de terminal). On
n'impose pas `command=` : `scp` et `ls` ont besoin d'exécuter des commandes. Cette clé donne donc
l'accès de `sam` : la garder sur le PC seulement.

```powershell
# Affiche la ligne à copier
Get-Content "$env:USERPROFILE\.ssh\hayaflash_backup_ed25519.pub"
```

Sur le VPS (connecté en `sam`) — remplacer `<LIGNE_PUBLIQUE>` par le contenu affiché :

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty <LIGNE_PUBLIQUE>' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Enregistrer l'empreinte du serveur (nécessaire car le script impose `StrictHostKeyChecking=yes`) :

```powershell
ssh -i "$env:USERPROFILE\.ssh\hayaflash_backup_ed25519" sam@31.207.39.116 "echo ok"   # répondre « yes » une fois
```

Protéger la clé privée : ne la copier nulle part ; si le PC est perdu, retirer la ligne
`hayaflash-backup-pull` de `authorized_keys`.

### 5.2 Premier essai puis planification quotidienne

```powershell
# Essai sans rien copier
powershell -ExecutionPolicy Bypass -File C:\projets\hayaflash\infra\scripts\windows\pull_backups.ps1 -CleAge age1... -SimulationSeulement
# Copie réelle (chiffrée)
powershell -ExecutionPolicy Bypass -File C:\projets\hayaflash\infra\scripts\windows\pull_backups.ps1 -CleAge age1...
```

Tâche planifiée tous les jours à 09:00, avec « exécuter dès que possible si l'heure est manquée »
(PC éteint à 09:00) :

```powershell
$action  = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\projets\hayaflash\infra\scripts\windows\pull_backups.ps1" -CleAge age1REMPLACER_PAR_LA_CLE_PUBLIQUE'
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'HayaFlash - copie des sauvegardes' -Action $action -Trigger $trigger -Settings $settings `
  -Description 'Tire les sauvegardes HayaFlash du VPS vers D:' 
```

Équivalent `schtasks` (sans l'option « dès que possible », à régler ensuite dans l'interface) :
`schtasks /Create /SC DAILY /ST 09:00 /TN "HayaFlash - copie des sauvegardes" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\projets\hayaflash\infra\scripts\windows\pull_backups.ps1 -CleAge age1..."`.
Si le disque D: est débranché à 09:00, la tâche échoue (code 1) et le journal le dit : rebrancher puis
relancer la tâche à la main.

## 6. Tester une restauration (à faire avant l'ouverture, puis chaque mois)

`restore_test.sh` ne touche **aucune** pile : il démarre un PostgreSQL jetable (nom unique,
`--network none`, données en mémoire, aucun volume), y restaure `db.dump`, compte les lignes de
`accounts_user`, `accounts_sellerprofile`, `flash_sales_flashsale`, `orders_order`, vérifie
l'archive des médias puis supprime le conteneur. Il se termine par **`RESTAURATION OK`**.

```bash
bash /srv/hayaflash-prod/infra/scripts/restore_test.sh /srv/backups/hayaflash-prod/<AAAA-MM-JJ_HHMM>
```

Sur le PC (Docker Desktop + Git Bash) le même script teste une sauvegarde de D: **après l'avoir
déchiffrée** avec `decrypt_backup.ps1` (§ 7.1) :
`bash infra/scripts/restore_test.sh "/c/Temp/restauration/<AAAA-MM-JJ_HHMM>"`.

## 7. Restaurer pour de vrai

**Destructif** : la base de la pile désignée est écrasée. À faire seulement en cas de sinistre,
après `restore_test.sh` sur la même sauvegarde.

```bash
# 1. Lire ce qui serait fait
bash /srv/hayaflash-prod/infra/scripts/restore.sh /srv/hayaflash-prod /srv/backups/hayaflash-prod/<AAAA-MM-JJ_HHMM> --dry-run
# 2. Restaurer (sauvegarde préalable automatique + double confirmation au clavier)
bash /srv/hayaflash-prod/infra/scripts/restore.sh /srv/hayaflash-prod /srv/backups/hayaflash-prod/<AAAA-MM-JJ_HHMM>
```

Garde-fous : refuse une sauvegarde d'un autre projet (sauf `--allow-other-project`), vérifie
`SHA256SUMS`, exige de taper le nom du projet puis `RESTAURER`, n'utilise jamais `down -v`,
`volume rm` ni `DROP DATABASE` (`pg_restore --clean --if-exists`, `web/worker/beat` arrêtés).

### 7.1 Depuis le disque D: (VPS perdu ou base détruite)

1. Brancher D: et la clé USB qui contient la clé privée `age`. Choisir le fichier le plus récent de
   `D:\Sauvegardes\HayaFlash\hayaflash-prod\` (`AAAA-MM-JJ_HHMM.tar.age`).
2. Déchiffrer vers un dossier **temporaire** (la sortie est en clair, ne pas la laisser sur D:) :
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\projets\hayaflash\infra\scripts\windows\decrypt_backup.ps1 `
     -Sauvegarde D:\Sauvegardes\HayaFlash\hayaflash-prod\<AAAA-MM-JJ_HHMM>.tar.age `
     -Sortie C:\Temp\restauration -CleSecrete E:\cles\hayaflash-age-PRIVEE.txt
   ```
   Le script vérifie les SHA256 et affiche `OK`. Le dossier obtenu est
   `C:\Temp\restauration\<AAAA-MM-JJ_HHMM>\`.
3. Le copier sur le (nouveau) VPS : `scp -r` du dossier vers `/srv/backups/hayaflash-prod/` (ou n'importe
   quel dossier lisible par `sam`).
4. Reconstruire la pile (`docs/RUNBOOK_JOUR_J.md` : clone, `.env`, `deploy_vps.sh`), puis
   `restore_test.sh` sur le dossier copié, puis `restore.sh` comme ci-dessus.
5. Vérifier `/health/`, la connexion d'un vendeur, une vente, une image produit.
6. Supprimer `C:\Temp\restauration` (copie en clair).

Le `.env` n'est **pas** dans la sauvegarde : le retrouver dans votre coffre à secrets.

## 8. Test manuel de la copie chiffrée (Windows — non automatisable ici)

À faire une fois après l'installation, puis après tout changement de clé :

1. `age --version` répond ; `D:` est branché ; `age-keygen` a été exécuté (§ 5.0), clé publique notée.
2. Simulation : `pull_backups.ps1 -CleAge age1... -SimulationSeulement` → affiche « N a copier »,
   ne crée rien.
3. Copie réelle : `pull_backups.ps1 -CleAge age1...` → « Copie vérifiée et chiffrée : …tar.age » ;
   code de sortie 0 (`$LASTEXITCODE`).
4. Aucun clair sur D: : `Get-ChildItem D:\Sauvegardes\HayaFlash\hayaflash-prod -Recurse` ne montre que
   des `*.tar.age` (aucun `db.dump`, aucun dossier `AAAA-MM-JJ_HHMM`, aucun `.tmp-*`) ;
   `%LOCALAPPDATA%\HayaFlash\tmp-backups` est vide.
5. Déchiffrement avec la clé **conservée hors du PC** (clé USB) : `decrypt_backup.ps1` → `OK`.
6. Mauvaise clé : avec une autre clé privée, le script doit échouer avec « mauvaise clé ? » (code 2).
7. `restore_test.sh` sur le dossier déchiffré → `RESTAURATION OK` ; supprimer le dossier en clair.
8. Disque absent : débrancher D: puis relancer → « Le disque D: est absent », code 1.
9. Fraîcheur : renommer provisoirement le dernier `.tar.age` avec une date de plus de 48 h → alerte
   jaune et code 3 (remettre le nom ensuite).
10. Tâche planifiée : l'exécuter à la main (`Start-ScheduledTask`) et lire `pull.log`.
