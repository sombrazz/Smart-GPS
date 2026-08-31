# Smart GPS

Smart GPS is a port-logistics simulator built around a FastAPI service, a Leaflet dashboard, and a small routing/simulation engine. It models vehicles moving through operational zones such as gates, rail yards, warehouses, piers, maintenance areas, and junctions.

The repository is a demonstrator rather than a production dispatch system. Authentication is mocked, the events and requests are synthetic, and the map graph is prepared from OpenStreetMap data.

## Features

- Supervisor and driver views over the same simulated operation.
- Vehicle movement along graph-backed routes with real edge geometry.
- Operational events such as congestion, blocked segments, and hotspots.
- Deterministic dispatch rules plus an optional scikit-learn model path.
- Synthetic datasets for comparing rule-based and model-assisted selection.
- JSON/CSV export endpoints for inspection and experiments.

## Architecture

```text
app/
  api/          REST endpoints
  core/         application settings
  data/         seed data and generated model artifacts
  ml/           feature preparation and inference
  routing/      graph loading and route selection
  simulation/   entities and simulation loop
  static/       dashboard JavaScript and CSS
  templates/    HTML entry point
scripts/        graph refresh and model training helpers
tests/          routing, dataset, and selection tests
```

## Stack

- Python 3
- FastAPI + Uvicorn
- NetworkX, OSMnx, and Shapely
- pandas, NumPy, and scikit-learn
- Leaflet with OpenStreetMap tiles

## Run locally

Create an environment and install the pinned dependencies:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Start the development server:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

Open [http://127.0.0.1:8010](http://127.0.0.1:8010).

The demo login is intentionally local and static:

```text
condutor@demo.com / demo123
supervisor@demo.com / demo123
```

Run the test suite with:

```powershell
pytest
```

## Useful endpoints

| Area | Endpoints |
| --- | --- |
| Auth | `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` |
| Dashboards | `GET /api/dashboard/driver`, `GET /api/dashboard/supervisor` |
| Simulation | `GET /api/state`, `POST /api/start`, `POST /api/pause`, `POST /api/reset`, `POST /api/step` |
| Planning | `POST /api/requests`, `POST /api/events`, `POST /api/strategy`, `POST /api/compare` |
| Export | `GET /api/export/csv`, `GET /api/export/json` |

## Model training

The sample dataset can be used to train the optional model artifacts:

```powershell
python scripts/train_model.py app/data/sample_synthetic_dataset.csv
```

Generated artifacts are read from `app/data/models/` when present. If a model is unavailable, the simulator falls back to deterministic rules.

## Notes

- Map data and tile usage follow the applicable OpenStreetMap/OSMnx terms.
- The project is intended for local experiments and UI demonstrations; it is not a safety-critical or production logistics controller.
