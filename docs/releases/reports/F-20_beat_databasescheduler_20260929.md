# Preuve F-20 — beat + DatabaseScheduler sur PostgreSQL (2026-09-29)

Commande : celery -A config beat -l debug --scheduler django_celery_beat.schedulers:DatabaseScheduler (20 s, DJANGO_SETTINGS_MODULE=config.settings.dev, DATABASE_URL=postgres 127.0.0.1:55432/hf_beat_proof — base jetable, supprimée).

```
    . scheduler -> django_celery_beat.schedulers.DatabaseScheduler
[2026-09-29 22:04:54,942: DEBUG/MainProcess] DatabaseScheduler: initial read
[2026-09-29 22:04:54,943: DEBUG/MainProcess] DatabaseScheduler: Fetching database schedule
<ModelEntry: auto-close-live-sales flash_sales.auto_close_live_sales(*[], **{}) <freq: 1.00 minute>>
[2026-09-29 22:04:55,446: INFO/MainProcess] DatabaseScheduler: Schedule changed.
[2026-09-29 22:04:55,446: DEBUG/MainProcess] DatabaseScheduler: Fetching database schedule
<ModelEntry: auto-close-live-sales flash_sales.auto_close_live_sales(*[], **{}) <freq: 1.00 minute>>
```
