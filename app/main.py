from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from app.core.settings import APP_HOST, APP_PORT, STATIC_DIR, TEMPLATES_DIR
from app.simulation.engine import SimulationEngine


simulation_engine = SimulationEngine()
simulation_engine.start()

app = FastAPI(title="Vale Port Logistics Simulator", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


from app.api.routes import router as api_router  # noqa: E402

app.include_router(api_router)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=APP_HOST, port=APP_PORT, reload=True)
