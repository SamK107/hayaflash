# Audit HayaFlash — Prêt au déploiement, performance & SEO

Basé sur lecture directe du code (`base.html`, `flash_sale_public.html`, `home.html`, `config/settings/*.py`, `requirements.txt`, `docs/CLAUDE.md`, `docs/CODEBASE_STATUS.md`, `docs/PLAN_PHASES.md`) le 13/09/2026.

## 1. Gouvernance — les phases prévues sont-elles vraiment terminées ?

Oui, fonctionnellement. `CLAUDE.md` et `CODEBASE_STATUS.md` sont cohérents entre eux et avec le code (P0 à P7 ✅). Mais "toutes les phases terminées" ne veut pas dire "prêt à déployer sans réserve" — trois points bloquent une mise en prod propre, indépendamment de tout ce qui suit :

| Point | Statut | Action |
|---|---|---|
| Migration `flash_sales/0010_saleinterest_reminded_at` | Écrite, **non appliquée** | `python manage.py migrate` au déploiement, sinon le rappel automatique des inscrits plante silencieusement |
| Suite de tests | Dernière mesure connue : 18/07 (103 passed, ~77% couverture) | À relancer avant tout déploiement — non ré-exécutée depuis, `notifications/` marqué "à compléter", pas de tests E2E |
| `deploy-staging`/`deploy-prod` (`deploy.yml`) | `if: false` — volontairement coupé le 13/09 (VPS pas prêt) | Attendu, mais ça veut dire que le pipeline "vert" ne prouve pas qu'un déploiement réel fonctionne. Retirer la ligne + tester une fois le VPS prêt |

Le point F3 "Sales Drawer" (gouvernance floue, cf. `CLAUDE.md` §11) n'est pas un blocant technique : le code existe (`orderDrawer` dans `flash_sale_public.html`), il manque juste une confirmation produit. Aucune action code requise avant déploiement.

**Aucun de ces trois points n'est un problème de performance ou de SEO** — ce sont des trous de process. Le reste de cet audit porte sur ce qui n'est *pas* dans la gouvernance actuelle mais qui compte pour un lancement "moderne".

## 2. Le vrai sujet : les CDN externes (`unpkg`, `jsdelivr`, `cdn.tailwindcss.com`, Google Fonts)

Réponse directe à ta question : **non, rien n'est vendorisé.** Tout `base.html` (qui est le layout de **toutes** les pages, y compris la page publique de vente flash `/f/<slug>/` — celle que les clients ouvrent depuis un lien WhatsApp sur mobile) charge cinq domaines externes avant même le premier rendu :

```html
<script src="https://cdn.tailwindcss.com"></script>                                  <!-- pas de version -->
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js">     <!-- version flottante 3.x.x -->
<script src="https://unpkg.com/htmx.org@2.0.0/dist/htmx.min.js"></script>           <!-- version figée, correct -->
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.js"></script>          <!-- @latest, aucune version -->
<link href="https://fonts.googleapis.com/css2?family=Inter...">                     <!-- non auto-hébergé -->
```

Et `home.html` en rajoute un sixième (Google Fonts Poppins, en plus d'Inter — deux familles de police Google chargées séparément sur la page d'accueil).

C'est pertinent pour la performance, et c'est même le point le plus important de cet audit, pour trois raisons :

**a) Coût réseau réel pour ton audience.** Chaque domaine externe = une résolution DNS + une poignée de main TLS supplémentaire avant de récupérer le fichier. Sur la 3G/4G à Bamako, ça se voit directement sur le LCP (Largest Contentful Paint) de la page qui compte le plus commercialement : la page de vente flash publique, ouverte depuis WhatsApp par un client qui n'a pas de cache déjà chaud sur ces CDN.

**b) `cdn.tailwindcss.com` n'est officiellement pas destiné à la production.** C'est le compilateur Tailwind complet (JIT) qui tourne dans le navigateur du client, recalcule le CSS à chaque chargement de page, et injecte un `<style>` — d'où le patch que tu as dû ajouter dans `base.html` (lignes 62-72 : `.bg-primary { ... !important }`) parce que "Tailwind CDN ne génère pas toujours les custom colors". C'est un symptôme direct du problème, pas juste une question de vitesse.

**c) Risque de rupture et de sécurité.** `alpinejs@3.x.x` et `lucide@latest` ne sont pas figés à une version précise — un nouveau build en amont (même mineur) peut changer de comportement sans que tu aies rien touché dans ton code, un jour de production, sans rollback possible côté client. Et sans intégrité de sous-ressource (SRI) sur aucun des quatre scripts, un CDN compromis peut injecter du JS arbitraire sur toutes tes pages — y compris les pages authentifiées vendeur.

### Recommandation concrète

Vendoriser (télécharger et servir depuis `static/vendor/`, géré par WhiteNoise comme le reste) :

1. **Tailwind** : ne pas vendoriser le CDN tel quel — le remplacer par un vrai build (Tailwind CLI, une seule commande `npx tailwindcss -i input.css -o static/css/tailwind.css --minify` avec purge automatique des classes inutilisées). Résultat : un fichier CSS de quelques dizaines de Ko au lieu du compilateur JS complet + le calcul refait à chaque page. Ça élimine aussi le hack `!important` sur les couleurs custom.
2. **HTMX 2.0.0** et **Alpine.js** (figer une version exacte, ex. `3.14.x`) : télécharger les fichiers minifiés dans `static/vendor/`, référencer via `{% static %}`.
3. **Lucide** : soit vendoriser une version exacte, soit — mieux, vu le nombre limité d'icônes utilisées (`wifi-off`, `x`, quelques autres) — passer à des SVG inline directement dans les templates. Zéro JS à parser, zéro dépendance externe pour un besoin aussi simple.
4. **Google Fonts** : auto-héberger les 1-2 polices réellement utilisées (fichiers `.woff2` dans `static/fonts/`) plutôt que dépendre de `fonts.googleapis.com`. Ça supprime une requête bloquante de plus et évite d'envoyer l'IP de chaque visiteur à Google avant même qu'il ait vu la page.
5. Sur `home.html` : choisir une seule famille de police marketing (Inter **ou** Poppins, pas les deux) pour éviter deux requêtes de police séparées.

Bénéfice supplémentaire, non négligeable : une fois tout vendorisé, une vraie **Content-Security-Policy** devient possible (aujourd'hui, avec 5 origines de script externes différentes, une CSP correcte serait très permissive et donc peu utile). C'est le chaînon manquant dans une configuration sécurité par ailleurs déjà solide (voir §4).

## 3. Images — CLS et poids de page

Sur `flash_sale_public.html` (la page produit publique) et `product_form.html` : les balises `<img>` (couverture de vente, photos produits) n'ont ni `loading="lazy"`, ni `width`/`height` explicites, ni `srcset` pour servir une taille adaptée au mobile. Conséquences concrètes :

- Chaque photo produit se charge en pleine résolution même hors écran → poids de page inutile sur une connexion mobile limitée.
- Sans dimensions réservées, le navigateur ne peut pas allouer l'espace avant chargement → CLS (Cumulative Layout Shift), la page "saute" pendant le chargement — mauvais signal Core Web Vitals et mauvaise UX sur la page qui doit convertir.
- Aucun pipeline de redimensionnement à l'upload (`Pillow` est présent mais utilisé tel quel, pas de génération de miniatures) : une photo vendeur prise en 12 Mpx avec un smartphone est servie telle quelle aux clients.

Actions concrètes, par ordre d'impact/effort :
1. Ajouter `loading="lazy" decoding="async"` sur toutes les images produits (sauf l'image de couverture au-dessus de la ligne de flottaison, qui doit au contraire être priorisée avec `fetchpriority="high"`).
2. Ajouter `width`/`height` (ou un `aspect-ratio` CSS) pour éliminer le CLS.
3. Générer une version redimensionnée (ex. max 800px de large) à l'upload — `Pillow` est déjà une dépendance, il ne manque qu'un `resize()` dans le service d'upload, ou une lib dédiée type `django-imagekit` si tu veux plusieurs formats (thumbnail, retina).

## 4. Ce qui est déjà bien fait (à ne pas casser)

Pour équilibrer — plusieurs choses sont déjà en place et suivent les bonnes pratiques :

- **Sécurité prod** (`config/settings/prod.py`) : HSTS 1 an + sous-domaines + preload, cookies `Secure`/`HttpOnly`, `SECURE_SSL_REDIRECT`, `X_FRAME_OPTIONS=DENY`, `SECURE_REFERRER_POLICY`, Argon2 pour les mots de passe. C'est du niveau attendu pour une prod sérieuse.
- **Fichiers statiques** : `WhiteNoise` avec `CompressedManifestStaticFilesStorage` — compression gzip + noms de fichiers hashés (cache-busting automatique) + cache long terme sur les fichiers hashés. C'est la bonne approche ; ajouter le paquet `Brotli` (pip) permettrait à WhiteNoise de précompresser aussi en Brotli, meilleur taux de compression que gzip sur les navigateurs qui le supportent (quasi tous).
- **SEO déjà en place** sur les pages publiques (`analytics/services/seo.py`, partiel `seo_head.html`) : balise canonique, Open Graph complet, Twitter Card, JSON-LD structuré. C'est plus que ce que beaucoup de projets similaires ont à ce stade.
- **`font-display: swap`** déjà utilisé sur les polices Google — évite le texte invisible pendant le chargement (bon réflexe, même si l'auto-hébergement reste préférable).

Ce qui manque côté SEO technique (pas trouvé dans le code) :
- Pas de `robots.txt` ni de `sitemap.xml` détecté. Pour un site avec des pages publiques indexables (`/f/<slug>/`, `/s/<slug>/`, `/ventes/`), c'est un manque simple à combler et à fort effet pour l'indexation Google.

## 5. Priorisation concrète

| Priorité | Action | Effort |
|---|---|---|
| 1 | Appliquer la migration en attente + relancer la suite de tests | Faible |
| 2 | Vendoriser Tailwind (vrai build CLI, pas juste télécharger le CDN), HTMX, Alpine, Lucide | Moyen — le gain le plus visible en performance et en fiabilité |
| 3 | Auto-héberger les polices Google, unifier sur une seule famille marketing | Faible |
| 4 | `loading="lazy"` + dimensions explicites sur les images produits | Faible |
| 5 | Redimensionnement des images à l'upload | Moyen |
| 6 | `robots.txt` + `sitemap.xml` | Faible |
| 7 | `Brotli` en plus de gzip sur WhiteNoise | Très faible |
| 8 | Content-Security-Policy (une fois le point 2 fait) | Moyen |

Les points 1 est un vrai blocant de déploiement. Les points 2 à 8 ne bloquent pas techniquement une mise en ligne (le site fonctionne aujourd'hui), mais c'est exactement l'écart entre "les phases prévues sont terminées" et "optimisé selon les pratiques modernes" que tu demandais de vérifier — et vu que la page la plus stratégique (vente flash publique, partagée sur WhatsApp) est aussi la plus pénalisée par les CDN non vendorisés, je la mettrais en premier après le point 1.
