# SPEC — Studio HayaFlash : nettoyage des photos produits (Évolution 2)

> Gouvernance : `GOVERNANCE_EVOLUTIONS.md`. Branche : `feature/studio`. Effort : 3–4 jours. Risque : moyen (mémoire du VPS partagé avec symain).

## Objectif

Depuis sa boutique, au moment de saisir les produits d'une vente flash, le vendeur appuie sur **« ✨ Nettoyer le fond »** : l'arrière-plan est supprimé, le produit est recadré et centré sur un fond uni (blanc, gris clair ou couleur de la boutique). Il voit l'avant/après et valide ou annule. **La photo d'origine n'est jamais modifiée ni supprimée.**

## Choix techniques (validés)

- Traitement **côté serveur** avec `rembg` (licence MIT), modèle `isnet-general-use`. Pas de traitement dans le navigateur (modèle de 40–80 Mo à télécharger : trop coûteux en data au Mali).
- **Worker Celery dédié**, file `studio`, isolé du worker existant.
- Compression côté téléphone avant envoi (≤ 1600 px, JPEG 0,85) pour économiser la data.
- Pas d'API payante en V1.

## Phase 0 — Go / no-go mémoire (obligatoire, sur le VPS de prod)

```bash
free -h
docker stats --no-stream
```
- **GO** si ≥ 2 Go de RAM disponibles en dehors des conteneurs actuels (le worker Studio est limité à 1,5 Go).
- **NO-GO** sinon : soit augmenter la RAM du VPS chez LWS, soit reporter. Décision écrite dans `docs/decisions/`.

## Phase 1 — App `studio` et modèle (migration additive)

Créer `core.FeatureFlag` si absent (voir gouvernance §3) puis :
```python
class CleanJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        RUNNING = "running", "En cours"
        DONE = "done", "Terminé"
        FAILED = "failed", "Échec"
        APPLIED = "applied", "Appliqué"
        DISCARDED = "discarded", "Annulé"

    seller = models.ForeignKey("accounts.SellerProfile", on_delete=models.CASCADE, related_name="clean_jobs")
    product = models.ForeignKey("products.Product", on_delete=models.CASCADE, null=True, blank=True)
    source_media = models.ForeignKey("products.ProductMedia", on_delete=models.SET_NULL, null=True, blank=True)
    source_image = models.ImageField(upload_to="studio/source/%Y/%m/")
    result_image = models.ImageField(upload_to="studio/result/%Y/%m/", blank=True)
    bg_color = models.CharField(max_length=7, default="#FFFFFF")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=255, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```
Quotas (configurables dans l'admin, comme les plans) : nouveau modèle `StudioQuota(plan, daily_limit)` — valeurs initiales FREE 5, MEDIUM 20, PRO 60 par jour.

## Phase 2 — Service de traitement

`studio/services/clean.py` :
```python
import io, time
from PIL import Image, ImageOps

_SESSION = None

def _session():
    global _SESSION
    if _SESSION is None:
        from rembg import new_session
        _SESSION = new_session("isnet-general-use")
    return _SESSION

def clean_image(data: bytes, bg_color: str = "#FFFFFF", size: int = 1080, margin: float = 0.85) -> bytes:
    from rembg import remove
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGBA")
    img.thumbnail((1600, 1600))
    cut = remove(img, session=_session())
    bbox = cut.getbbox()
    if bbox is None:
        raise ValueError("Aucun produit détecté sur la photo")
    cut = cut.crop(bbox)
    cut.thumbnail((int(size * margin), int(size * margin)))
    canvas = Image.new("RGBA", (size, size), bg_color)
    canvas.alpha_composite(cut, ((size - cut.width) // 2, (size - cut.height) // 2))
    out = io.BytesIO()
    canvas.convert("RGB").save(out, "WEBP", quality=82, method=4)
    return out.getvalue()
```
`studio/tasks.py` : tâche `run_clean_job(job_id)` sur la file `studio`, `time_limit=90`, `soft_time_limit=60`, **sans retry automatique** ; renseigne `status`, `duration_ms`, `error` (message en français lisible par le vendeur).

**Appliquer** (service `apply_clean_job`) : crée un **nouveau** `ProductMedia` avec l'image nettoyée, placé en première position ; l'ancien média reste attaché (le vendeur peut le supprimer lui-même). Statut → `applied`.

## Phase 3 — Docker (seule zone d'infra modifiée)

1. `requirements-studio.txt` : `rembg[cpu]` et `onnxruntime` (versions épinglées).
2. Dockerfile : installer ces dépendances et **télécharger le modèle au build** :
   ```dockerfile
   ENV U2NET_HOME=/opt/models
   RUN python -c "from rembg import new_session; new_session('isnet-general-use')"
   ```
3. `docker-compose.production.yml` (et `docker-compose.yml`) : **nouveau service**, le worker existant n'est pas modifié :
   ```yaml
   worker-studio:
     <<: *app-common          # même ancre que le worker existant
     command: celery -A config worker -l info -c 1 -Q studio --max-tasks-per-child 50
     mem_limit: 1536m
     cpus: 1.0
   ```
4. `CELERY_TASK_ROUTES` : `{"studio.tasks.*": {"queue": "studio"}}`.

## Phase 4 — Interface vendeur

- Bouton « ✨ Nettoyer le fond » sous chaque photo, dans le formulaire produit et la Publication rapide, **affiché seulement si** `is_enabled("studio", seller)`.
- Flux HTMX : envoi → création `CleanJob` → interrogation du statut toutes les 2 s (arrêt après 90 s) → avant/après côte à côte → pastilles de couleur (blanc `#FFFFFF`, gris clair `#F3F4F6`, couleur de la boutique) → « Utiliser cette photo » / « Garder l'originale ».
- Changer de couleur relance le traitement (compte dans le quota).
- Conseil affiché : « Pose le produit sur une surface unie, en lumière du jour. »
- Quota atteint : message clair + mention du plan supérieur.

## Phase 5 — Tests

- Service : `rembg.remove` **mocké** dans les tests unitaires (CI rapide) ; 1 test d'intégration réel marqué `@pytest.mark.slow`, hors CI par défaut.
- Permissions : un vendeur ne peut ni lancer ni appliquer un job sur le produit d'un autre.
- Quota par plan et par jour.
- Flag éteint → bouton absent, endpoints renvoient 404.
- Appliquer → nouveau `ProductMedia`, original intact.

## Recette staging (checklist)

- [ ] 15 vraies photos de téléphone : tissu, chaussure, cosmétique, bijou, sac, objet sombre sur fond sombre
- [ ] Temps moyen < 5 s ; `docker stats` : worker-studio < 1,5 Go, autres services inchangés
- [ ] 5 nettoyages lancés en même temps : traités l'un après l'autre, aucun plantage
- [ ] Flag ON / OFF pour un vendeur de test
- [ ] symain.africa et services.symain.africa restent réactifs pendant les tests

## Mise en prod

Process gouvernance §6, observation staging 48 h. Activation : 1 vendeur pilote, puis 3, puis tous. Indicateurs suivis la 1re semaine : nombre de jobs, taux d'échec, durée moyenne, pic mémoire.
