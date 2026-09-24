# Tester HayaFlash sur téléphone en HTTPS local (PWA, micro, GPS)

Chrome n'installe une PWA (et n'autorise micro / géolocalisation) que sur une
origine sécurisée : `https://…` ou `localhost`. Une adresse `http://192.168.x.x:8000`
depuis un téléphone **ne propose jamais** l'installation. Deux options :

- **ngrok** (HTTPS public, voir `config/settings/dev.py`) ;
- **HTTPS local sur le Wi-Fi** avec `mkcert` (ce document) : plus rapide, pas
  d'URL qui change, fonctionne sans Internet.

## 1. Une fois par PC

```powershell
winget install FiloSottile.mkcert
mkcert -install        # ajoute l'autorité mkcert aux certificats de confiance du PC
```

## 2. Lancer le serveur HTTPS

```powershell
.venv\Scripts\python.exe manage.py runserver_https --settings=config.settings.dev
```

- Écoute sur `0.0.0.0:8443` et affiche les adresses utilisables
  (`https://localhost:8443/`, `https://<IP du PC>:8443/`).
- Au premier lancement, le certificat est créé dans `.certs/` (ignoré par git)
  pour `localhost`, `127.0.0.1` et les IP locales du PC.
- **L'IP du PC a changé** (autre Wi-Fi, partage de connexion, DHCP) : le certificat est
  **refait automatiquement** au lancement (`.certs/hosts.txt`). Important : Chrome ne propose
  **jamais** l'installation sur une page en erreur de certificat, même après « Continuer quand
  même » — le bandeau HayaFlash retombe alors sur les instructions manuelles (menu ⋮).
- `ALLOWED_HOSTS` inclut automatiquement les IP locales en dev : rien à mettre
  dans `.env`.
- Au premier lancement, Windows peut demander d'autoriser Python sur le
  réseau : cocher **Réseaux privés**.
- Le serveur `runserver` habituel (port 8000) peut tourner en parallèle.

## 3. Une fois par téléphone Android : faire confiance au certificat

1. Récupérer le fichier `rootCA.crt` du PC : `mkcert -CAROOT` affiche le dossier
   (ex. `C:\Users\<vous>\AppData\Local\mkcert\rootCA.crt`). **Ne jamais partager
   `rootCA-key.pem`.**
2. Le copier sur le téléphone (câble USB, Drive…).
3. Paramètres → Sécurité → Chiffrement et identifiants → **Installer un
   certificat** → **Certificat CA** → choisir `rootCA.crt`.
4. Ouvrir `https://<IP du PC>:8443/` dans **Chrome** (pas le navigateur intégré
   de WhatsApp) : cadenas sans avertissement.

iPhone : AirDrop/mail du `rootCA.crt` → Réglages → Profil téléchargé →
Installer, puis Réglages → Général → Informations → Réglages des certificats
→ activer la confiance totale.

## 4. Tester l'installation

- Si l'app est **déjà installée** sur l'appareil, Chrome ne propose rien
  (`Ouvrir dans l'appli` dans la barre d'adresse sur PC) : la désinstaller
  d'abord (PC : `chrome://apps` → clic droit → Supprimer de Chrome).
- Valider l'invitation HayaFlash → fenêtre Chrome « Installer ? » → message
  **« HayaFlash est installée ✓ »** et icône sur l'écran d'accueil / le bureau.
- Si Chrome n'a pas d'installation à proposer, le bouton affiche désormais un
  message d'aide au lieu de ne rien faire (`static/js/hf-install.js`).
- **Refaire le test plusieurs fois sur le même téléphone** : l'invitation n'est montrée que
  2 fois par appareil. Pour repartir de zéro : Chrome → ⋮ → Paramètres → Paramètres des sites →
  Toutes les données des sites → l'adresse du PC → **Effacer et réinitialiser**.
