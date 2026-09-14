# Vendoring front — comment ça marche, comment le maintenir

> Créé le 14/09, suite à l'audit `docs/AUDIT_PERFORMANCE_SEO.md`. Avant cette
> date, Tailwind/HTMX/Alpine/Lucide/polices étaient chargés depuis des CDN
> externes (unpkg, jsdelivr, cdn.tailwindcss.com, fonts.googleapis.com).

## Ce qui a changé

| Lib | Avant | Maintenant |
|---|---|---|
| Tailwind CSS | `cdn.tailwindcss.com` (JIT compilé dans le navigateur à chaque page) | `static/vendor/tailwind/tailwind-hayaflash.css` — build statique via Tailwind CLI, purgé, minifié |
| HTMX | `unpkg.com/htmx.org@2.0.0` | `static/vendor/htmx/htmx-2.0.0.min.js` |
| Alpine.js | `cdn.jsdelivr.net/npm/alpinejs@3.x.x` (version flottante) | `static/vendor/alpinejs/alpine-3.14.9.min.js` (figée) |
| Lucide icons | `unpkg.com/lucide@latest` (aucune version figée) | `static/vendor/lucide/lucide-0.462.0.min.js` (figée, build complet non tree-shaké — voir "Limites" plus bas) |
| Police Inter | `fonts.googleapis.com` | `static/fonts/inter/*.woff2` + `inter.css` |
| Police Poppins (home.html) | `fonts.googleapis.com` | `static/fonts/poppins/*.woff2` + `poppins.css` |

Tous ces fichiers sont servis par WhiteNoise comme le reste de `static/`
(compression gzip/brotli + cache long terme automatique via le manifest).

## ⚠️ Le point important : Tailwind n'est plus un JIT

Avec le CDN, ajouter une classe Tailwind dans un template suffisait — le
compilateur tournait dans le navigateur du client et générait le CSS à la
volée. **Ce n'est plus le cas.** `tailwind-hayaflash.css` est un fichier figé,
généré une fois pour toutes les classes trouvées dans les templates *au
moment du build*. Si tu ajoutes une nouvelle classe Tailwind (`bg-teal-500`,
`grid-cols-5`, etc.) dans un template et que tu ne relances pas le build,
**cette classe n'existera simplement pas dans le CSS livré** — le navigateur
l'ignorera silencieusement (pas d'erreur, juste un style manquant).

### Comment reconstruire le CSS

Il faut Node.js (n'importe quelle machine, y compris juste pour ce build —
pas besoin que ce soit le serveur de prod) :

```bash
mkdir -p /tmp/hf-tailwind-build && cd /tmp/hf-tailwind-build
npm init -y
npm install tailwindcss@3.4.17 --save-exact
```

Créer `tailwind.config.js` :

```js
module.exports = {
  content: [
    "<CHEMIN_VERS_LE_PROJET>/templates/**/*.html",
    "<CHEMIN_VERS_LE_PROJET>/static/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#FF4D2E',   // couleur de marque réelle (voir note ci-dessous)
        gold:    '#FFB800',
        dark:    '#111111',
        success: '#22C55E',
        warning: '#F59E0B',
        danger:  '#EF4444',
        muted:   '#6B7280',
        surface: '#FFFFFF',
        bg:      '#F5F5F5',
      },
      borderRadius: { '2xl': '1rem', '3xl': '1.5rem' },
      boxShadow: {
        sm: '0 1px 3px rgba(0,0,0,0.08)',
        md: '0 4px 12px rgba(0,0,0,0.12)',
      },
    }
  },
  safelist: [
    // Classes construites dynamiquement en JS (template strings) que le
    // scanner statique de Tailwind ne peut pas voir dans les .html/.js.
    { pattern: /^(bg|text|border|ring)-(primary|gold|success|warning|danger|muted)(\/\d+)?$/ },
    { pattern: /^(bg|text|border)-(red|green|amber|gray|zinc)-(50|100|200|300|400|500|600|700|800|900)$/ },
  ],
  plugins: [],
}
```

Créer `input.css` :

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

Builder :

```bash
npx tailwindcss -c tailwind.config.js -i input.css -o tailwind-hayaflash.css --minify
```

Puis remplacer `static/vendor/tailwind/tailwind-hayaflash.css` par le fichier
généré, et `python manage.py collectstatic` avant déploiement.

### Note sur la couleur `primary`

L'ancienne config CDN (dans l'historique de `base.html`) déclarait
`primary: '#E63946'`, mais un hack CSS `!important` dans le même fichier et le
`<meta name="theme-color">` utilisaient déjà `#FF4D2E` partout ailleurs —
`#FF4D2E` était donc la vraie couleur de marque en production, la config
Tailwind était juste restée désynchronisée. Le build ci-dessus utilise
`#FF4D2E` et le hack `!important` a été supprimé (plus nécessaire : le vrai
compilateur Tailwind génère correctement les couleurs custom, contrairement
au CDN qui avait ce problème). **Si la charte doit encore changer, c'est ici
qu'il faut le faire, puis relancer le build.**

## Limites connues (pas corrigées dans cette passe, volontairement)

- **Lucide (356 Ko minifié)** : la version vendorisée est le build complet
  (toutes les icônes de la librairie), pas seulement les ~67 icônes
  réellement utilisées par le site (`grep -rhoE 'data-lucide="[a-z0-9-]+"' templates/`
  pour la liste). Un tree-shaking custom (bundler + import individuel des
  icônes utilisées) ferait tomber ça à ~15-20 Ko, mais n'a pas été fait ici
  car impossible à vérifier visuellement sans pouvoir lancer le serveur Django
  (accès shell direct à la machine indisponible au moment de ce chantier — cf.
  bug Windows connu côté pont Claude). À faire quand tu peux tester en live.
- **CSP en Report-Only** : voir `config/settings/base.py` — ne bloque rien
  tant que les nombreux `onclick=""`/`<script>` inline n'ont pas été migrés
  vers des gestionnaires d'événements externes. Vérifier la console
  navigateur sur staging avant d'envisager `CSP_REPORT_ONLY = False`.
