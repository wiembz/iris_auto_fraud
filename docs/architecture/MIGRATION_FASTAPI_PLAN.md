# Migration de l'API IRIS : Flask → FastAPI

> Fait le 2026-08-12, sur la branche `migration-fastapi`. Migration
> d'équivalence fonctionnelle : mêmes endpoints `/api/...`, mêmes réponses
> JSON, mêmes statuts HTTP, mêmes erreurs `{"message": "..."}`. Aucune
> logique métier modifiée — seule la couche API a changé.

## Pourquoi

Flask (WSGI) ne fournit ni validation de schéma, ni documentation OpenAPI
automatique, ni distinction claire entre routes synchrones et asynchrones.
FastAPI (ASGI, Starlette + Pydantic) apporte tout ça nativement, sans
toucher aux services métier déjà validés (scoring, VHS, décisions,
workflow, audit).

## Ce qui a changé

| Avant (Flask) | Après (FastAPI) |
|---|---|
| `backend/routes/*.py` (8 fichiers, `Blueprint`) | `backend/api/routers/*.py` (8 fichiers, `APIRouter`) |
| `current_app.config["IRIS_ENGINE"]` | `Depends(get_db_engine)` (`backend/api/dependencies.py`) |
| `request.args.get(...)` | Paramètres de fonction (query params typés) |
| `request.get_json(silent=True) or {}` | Modèles Pydantic (`backend/api/schemas.py`), tous les champs optionnels comme avant |
| `jsonify(...), status` | Retour natif + `status_code=...` sur le décorateur |
| `send_file(...)` | `FileResponse(...)` |
| `abort(404)` | `raise message_error(404, "...")` |
| `flask_cors.CORS` | `CORSMiddleware` |
| `app.test_client()` | `fastapi.testclient.TestClient` |

## Ce qui n'a PAS changé

- `backend/services/*` — intégralement inchangé, aucune ligne touchée.
- `backend/config.py`, `backend/db.py` — inchangés (juste un docstring corrigé).
- Les 28 endpoints `/api/...` : mêmes chemins, mêmes méthodes, mêmes réponses.
- Le port : `5000`, comme avant — le frontend Angular n'a nécessité aucune
  modification (`apiBaseUrl` déjà en dur sur `127.0.0.1:5000/api`).
- Le format d'erreur métier `{"message": "..."}` (voir `backend/api/errors.py`).
- Les statuts HTTP (201 sur création, 404/400/403 sur erreurs métier).

## Piège trouvé et corrigé pendant la migration

Toutes les routes avaient d'abord été écrites en `async def`, alors que les
services métier font des appels SQLAlchemy **synchrones**. Une route
`async def` qui appelle du code synchrone bloquant bloque toute la boucle
d'événements FastAPI — testé concrètement : une requête lente sur
`/api/portfolio/insights` bloquait `/api/health` derrière elle. Corrigé en
déclarant les routes en `def` simple (FastAPI les exécute alors dans un
threadpool automatiquement) ; seul `auth.py` reste `async def` car il fait
un `await request.json()` sans aucun appel bloquant derrière.

## Découverte incidente, hors scope de cette migration

`get_portfolio_insights()` (`backend/services/portfolio_insights_service.py`,
code métier non touché ici) a mis plus de 2h à s'exécuter en base lors des
tests de validation, sans jamais terminer — un vrai problème de performance
pré-existant, indépendant de Flask ou FastAPI (même service, même SQL,
même moteur). Probablement jamais remarqué en production. **À investiguer
séparément**, pas corrigé dans le cadre de cette migration (consigne
explicite : ne pas toucher à la logique métier).

## Validation effectuée

- `python -m pytest` : 272/272 passent (264 existants + 8 nouveaux tests de
  contrat `tests/test_fastapi_contract.py`).
- `tests/test_auth_service.py` migré vers `fastapi.testclient.TestClient`.
- `tests/test_backend_readonly_api.py` : le test qui inspectait le texte
  source des routes Flask inspecte maintenant `app.openapi()["paths"]`.
- `/docs` et `/openapi.json` répondent 200.
- Testé en conditions réelles (`uvicorn` + base de données vivante, pas
  seulement `TestClient`) : `/api/health`, `/api/summary`, `/api/claims`,
  `/api/claims/{id}` (200 et 404), `/api/vhs/overview`, `/api/vhs/vehicles`,
  `/api/vhs/inspection-images/{id}/content` (JPEG servi avec le bon
  Content-Type, 404 JSON si absent), `/api/claims/{id}/decision` et
  `/api/claims/{id}/workflow/status` (erreur métier 400 avec `{"message"}`,
  pas un 422 Pydantic), CORS preflight, `/api/decisions`, `/api/workflow/tasks`.
- `backend/routes/` (ancien code Flask) supprimé — aucun import Flask ne
  subsiste dans `backend/`.
- Dépendances mises à jour : `backend/requirements.txt` et `pyproject.toml`
  (retiré `Flask`/`flask-cors`, ajouté `fastapi`, `uvicorn[standard]`,
  `pydantic`, `httpx` en dev).

## Commande de lancement

```
uvicorn backend.app:app --host 127.0.0.1 --port 5000 --reload
```

## Phrase soutenance

> La migration vers FastAPI modernise la couche API d'IRIS en renforçant la
> validation, la documentation automatique (OpenAPI) et la maintenabilité,
> tout en conservant à l'identique les services métier déjà validés et les
> contrats consommés par Angular.
