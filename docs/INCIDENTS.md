# Registre des incidents & correctifs de sécurité — HayaFlash

> Référencé par `GOVERNANCE_SECURITE.md` (catégorie 10). Une ligne par
> incident de production, alerte de sécurité ou CVE corrigée — même mineure.
> Objectif : qu'un repreneur du projet sache ce qui s'est déjà produit et
> pourquoi certains garde-fous existent.
>
> Les bugs trouvés en audit **avant** la mise en production restent dans
> `docs/CODEBASE_STATUS.md` (ex. Phase 10.0) ; ici, uniquement ce qui a touché
> (ou aurait pu toucher) un environnement réel ou une donnée réelle.

## Comment remplir

| Champ | Contenu |
|---|---|
| Date | Date de détection (AAAA-MM-JJ) |
| Env | prod / staging |
| Type | panne · sécurité · données · paiement · CVE |
| Gravité | critique · majeure · mineure |
| Résumé | Ce qui s'est passé, en une phrase |
| Impact | Qui/quoi a été touché, combien de temps |
| Cause | Cause racine, pas le symptôme |
| Correctif | Commit/PR + action préventive ajoutée (test, alerte, doc) |

Sources de détection à surveiller : alertes Sentry (`environment=prod`/`staging`),
échec du workflow « Audit dépendances (CVE) » (email GitHub du lundi),
heartbeat des sauvegardes manquant, monitoring externe `/health/`.

## Journal

| Date | Env | Type | Gravité | Résumé | Impact | Cause | Correctif |
|---|---|---|---|---|---|---|---|
| — | — | — | — | Aucun incident enregistré (projet pas encore en production au 2026-09-24) | — | — | — |
