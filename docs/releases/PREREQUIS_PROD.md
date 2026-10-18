# Prérequis de la production — actions du porteur du projet

> Checklist des actions qui ne peuvent pas être faites depuis le dépôt. À cocher dans l'ordre.
> Aucune valeur secrète ne s'écrit dans ce fichier ni dans le dépôt : elles vont dans le `.env` de la pile
> concernée (`/srv/hayaflash-prod/.env`, droits 600) ou dans le gestionnaire de mots de passe.
> Contrôle automatique côté serveur (lecture seule) : `bash infra/scripts/check_prod_prereqs.sh`.

## 1. DNS chez LWS — `hayaflash.com` et `www.hayaflash.com`

- [ ] Où : espace client LWS → noms de domaine → `hayaflash.com` → zone DNS.
- [ ] Comment : un enregistrement **A** pour `@` (domaine nu) et un **A** pour `www`, tous deux vers `31.207.39.116`,
  TTL 300 s ; **aucun enregistrement AAAA** vers une autre machine ; pas de CNAME sur `@`.
- [ ] Vérifier : `dig +short hayaflash.com @1.1.1.1` et `@8.8.8.8` (idem pour `www`) renvoient `31.207.39.116`
  (le script `check_prod_prereqs.sh` le fait).
- [ ] `www` doit aussi être **déclaré comme alias du domaine dans HestiaCP** et couvert par le **certificat**
  Let's Encrypt (sinon `https://www.hayaflash.com` échoue avant la redirection vers le domaine nu).

## 2. Orange Money — clés de **production** (pas le bac à sable)

- [ ] Où : portail marchand Orange Money Mali (compte marchand).
- [ ] Récupérer les identifiants **de production** : client id, client secret, clé marchand.
  Ne jamais réutiliser ceux du staging s'il est en bac à sable.
- [ ] Enregistrer chez Orange les URL de la production (domaine `hayaflash.com`) :
  - retour : `https://hayaflash.com/billing/return/`
  - annulation : `https://hayaflash.com/billing/cancel/`
  - notification (webhook) : `https://hayaflash.com/billing/webhook/orange/`
- [ ] Les mettre dans `/srv/hayaflash-prod/.env` : `ORANGE_ML_CLIENT_ID`, `ORANGE_ML_CLIENT_SECRET`,
  `ORANGE_ML_MERCHANT_KEY`, `ORANGE_ML_BASE_URL=https://hayaflash.com` (et `ORANGE_ML_RETURN_URL`,
  `ORANGE_ML_CANCEL_URL`, `ORANGE_ML_NOTIFY_URL` si fixées à la main).
- [ ] Rejouer le paiement réel à 100 FCFA sur la prod (`docs/RUNBOOK_TEST_PAIEMENT.md`), puis fermer le tarif spécial.

## 3. Sentry — projet de production distinct

- [ ] Où : sentry.io → créer un **nouveau projet** (Django) réservé à la prod ; celui du staging ne change pas.
- [ ] Copier son DSN (secret) ; l'ajouter **à la main** dans `/srv/hayaflash-prod/.env` : `SENTRY_DSN=...`.
- [ ] Recréer les conteneurs avec `bash infra/scripts/deploy_vps.sh /srv/hayaflash-prod` (un `restart` ne relit pas le
  `.env`), puis déclencher une erreur de test (`docs/RUNBOOK_JOUR_J.md` § 4.1) et vérifier qu'elle arrive sans
  numéro de téléphone ni e-mail.
- [ ] Règles d'alerte e-mail sur `environment:prod` (`docs/RUNBOOK_JOUR_J.md` § 4.2).

## 4. E-mail — SMTP LWS

- [ ] Où : espace client LWS → messagerie → boîte `contact@hayaflash.com` (ou boîte d'envoi dédiée).
- [ ] Renseigner dans `/srv/hayaflash-prod/.env` : `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST` (serveur sortant LWS, ex. `mail.hayaflash.com`),
  `EMAIL_PORT=465`, `EMAIL_USE_SSL=true`, `EMAIL_HOST_USER` (l'adresse), `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`
  (noms exacts : voir `.env.example`).
- [ ] Tester : `docker compose -f docker-compose.production.yml exec -T web python manage.py send_test_email <adresse>`.
- [ ] Enregistrements **SPF, DKIM, DMARC** du domaine chez LWS (zone DNS), sinon les e-mails finissent en spam.

## 5. Sauvegardes sur le disque D: du PC Windows (chiffrées)

- [ ] Installer `age` : `winget install FiloSottile.age`.
- [ ] Créer la paire de clés `age` (`age-keygen`), noter la clé **publique** `age1…`, mettre la clé **privée** hors du PC
  (clé USB séparée + copie papier ou gestionnaire de mots de passe) puis la supprimer du PC — `docs/SAUVEGARDES.md` § 5.0.
- [ ] Créer la clé SSH dédiée `ed25519` et l'ajouter dans `~/.ssh/authorized_keys` de `sam` sur le VPS —
  `docs/SAUVEGARDES.md` § 5.1.
- [ ] Planifier la tâche Windows quotidienne (09:00, « dès que possible ») — `docs/SAUVEGARDES.md` § 5.2.
- [ ] Dérouler le test manuel de `docs/SAUVEGARDES.md` § 8 (copie, aucun clair sur D:, déchiffrement avec la clé de secours).

## 6. Serveur (VPS) — à lancer par le porteur, en lecture seule

- [ ] `bash infra/scripts/check_prod_prereqs.sh` : DNS, pare-feu (seuls 22, 80, 443, 8083 publics), ports 8020/8021 en
  `127.0.0.1`, PostgreSQL d'hôte non exposé, disque et mémoire, `symain.africa` et `services.symain.africa` en HTTPS.
  Aucun ÉCHEC toléré ; relire chaque ATTENTION.
- [ ] Avant tout rechargement du nginx de HestiaCP : `sudo nginx -t`, puis vérifier `symain.africa` et
  `services.symain.africa` (`RUNBOOK_JOUR_J.md`).

## 7. Divers

- [ ] Variables légales dans le `.env` de prod : `LEGAL_ENTITY_RCCM`, `LEGAL_ENTITY_ADDRESS`, `LEGAL_HOST_*` (LWS) —
  affichées dans les mentions légales.
- [ ] `ALLOWED_HOSTS` de prod contient `hayaflash.com`, `www.hayaflash.com` **et `localhost`** (healthcheck du conteneur) ;
  `CSRF_TRUSTED_ORIGINS=https://hayaflash.com` ; **aucune** variable `HAYAFLASH_ALLOW_DEMO_SEED`.
- [ ] Domaine Hestia sans `access_log`, certificat Let's Encrypt, vhost non régénéré (`RUNBOOK_JOUR_J.md`, F-65/F-145).
