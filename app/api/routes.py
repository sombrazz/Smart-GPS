from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth import authenticate_user, create_session, get_user_by_token, revoke_session
from app.main import simulation_engine


router = APIRouter(prefix="/api", tags=["simulation"])


class SpeedPayload(BaseModel):
    multiplier: float = Field(..., ge=0.25, le=8.0)


class RuntimePayload(BaseModel):
    ticks_enabled: bool = False
    tick_seconds: int = Field(default=10, ge=5, le=60)


class EventPayload(BaseModel):
    event_type: str
    edge: tuple[int | str, int | str]
    edge_key: int | str | None = None
    severity: float = Field(default=1.0, ge=0.1, le=1.0)
    duration_ticks: int = Field(default=10, ge=1, le=120)
    manual: bool = True


class RequestPayload(BaseModel):
    team_id: str | None = None


class StrategyPayload(BaseModel):
    strategy: str


class DebugPayload(BaseModel):
    enabled: bool


class SyntheticPayload(BaseModel):
    scenarios: int = Field(default=500, ge=10, le=10000)


class ScenarioPayload(BaseModel):
    vehicle_count: int = Field(default=5, ge=1, le=60)
    team_count: int = Field(default=5, ge=1, le=120)


class ComparePayload(BaseModel):
    steps: int = Field(default=30, ge=1, le=300)
    scenarios: int = Field(default=5, ge=1, le=50)


class LoginPayload(BaseModel):
    identifier: str
    password: str


def _resolve_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization[7:]
    return authorization


def _require_user(authorization: str | None):
    user = get_user_by_token(_resolve_token(authorization))
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


def _require_role(user: dict, role: str):
    if user["role"] != role:
        raise HTTPException(status_code=403, detail="forbidden")
    return user


@router.post("/auth/login")
def login(payload: LoginPayload):
    user = authenticate_user(payload.identifier, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    token = create_session(user["email"])
    return {"token": token, "user": user}


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    revoke_session(_resolve_token(authorization))
    return {"ok": True}


@router.get("/auth/me")
def me(authorization: str | None = Header(default=None)):
    user = _require_user(authorization)
    return {"user": user}


@router.get("/state")
def get_state():
    return simulation_engine.get_state()


@router.get("/dashboard/driver")
def get_driver_dashboard(vehicle_id: str | None = None, authorization: str | None = Header(default=None)):
    user = _require_role(_require_user(authorization), "driver")
    selected_vehicle_id = vehicle_id or user["vehicle_id"]
    dashboard = simulation_engine.get_driver_dashboard(selected_vehicle_id)
    dashboard["vehicle_options"] = [
        {"id": vehicle.id, "type": vehicle.vehicle_type}
        for vehicle in simulation_engine.vehicles.values()
    ]
    dashboard["selected_vehicle_id"] = selected_vehicle_id
    return dashboard


@router.get("/dashboard/supervisor")
def get_supervisor_dashboard(authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    return simulation_engine.get_supervisor_dashboard()


@router.get("/assets/{asset_id}")
def get_asset_details(asset_id: str, authorization: str | None = Header(default=None)):
    _require_user(authorization)
    asset = simulation_engine.get_asset_details(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="asset_not_found")
    return asset


@router.post("/start")
def start_simulation(authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    simulation_engine.start()
    return simulation_engine.get_state()


@router.post("/pause")
def pause_simulation(authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    simulation_engine.pause()
    return simulation_engine.get_state()


@router.post("/reset")
def reset_simulation(authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    simulation_engine.reset()
    return simulation_engine.get_state()


@router.post("/step")
def step_simulation(steps: int = 1, authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    if steps < 1 or steps > 30:
        raise HTTPException(status_code=400, detail="steps must be between 1 and 30")
    return simulation_engine.step(steps)


@router.post("/speed")
def set_speed(payload: SpeedPayload, authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    simulation_engine.set_speed(payload.multiplier)
    return simulation_engine.get_state()


@router.post("/runtime")
def set_runtime(payload: RuntimePayload, authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    simulation_engine.configure_runtime(
        ticks_enabled=payload.ticks_enabled,
        tick_seconds=payload.tick_seconds,
    )
    return simulation_engine.get_state()


@router.post("/strategy")
def set_strategy(payload: StrategyPayload, authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    simulation_engine.set_strategy(payload.strategy)
    return simulation_engine.get_state()


@router.post("/debug")
def set_debug(payload: DebugPayload, authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    simulation_engine.set_debug_mode(payload.enabled)
    return simulation_engine.get_state()


@router.post("/events")
def create_event(payload: EventPayload, authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    event = simulation_engine.create_event(
        event_type=payload.event_type,
        edge=payload.edge,
        edge_key=payload.edge_key,
        severity=payload.severity,
        duration_ticks=payload.duration_ticks,
        manual=payload.manual,
    )
    return {"event": event, "state": simulation_engine.get_state()}


@router.post("/requests")
def create_request(payload: RequestPayload, authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    team = simulation_engine.create_manual_request(payload.team_id)
    return {"team": team, "state": simulation_engine.get_state()}


@router.post("/synthetic")
def generate_synthetic(payload: SyntheticPayload, authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    rows = simulation_engine.generate_synthetic_scenarios(payload.scenarios)
    return {"generated_rows": len(rows), "total_rows": len(simulation_engine.synthetic_records)}


@router.post("/scenario")
def configure_scenario(payload: ScenarioPayload, authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    return simulation_engine.configure_scenario(payload.vehicle_count, payload.team_count)


@router.post("/compare")
def compare_strategies(payload: ComparePayload, authorization: str | None = Header(default=None)):
    _require_role(_require_user(authorization), "supervisor")
    comparison = simulation_engine.compare_strategies(payload.steps, payload.scenarios)
    return {"comparison": comparison, "state": simulation_engine.get_state()}


@router.get("/export/{file_format}")
def export_dataset(file_format: str):
    if file_format not in {"csv", "json"}:
        raise HTTPException(status_code=400, detail="format must be csv or json")
    path = simulation_engine.export_dataset(file_format)
    return FileResponse(path, filename=path.name)
