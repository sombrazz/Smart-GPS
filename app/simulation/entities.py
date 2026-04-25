from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Hashable


class VehicleStatus(str, Enum):
    IDLE = "idle"
    EN_ROUTE = "en_route"
    ASSISTING = "assisting"
    RETURNING = "returning"
    UNAVAILABLE = "unavailable"


class TeamPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Vehicle:
    id: str
    vehicle_type: str
    current_node: Hashable
    position: tuple[float, float]
    speed_kmh: float
    current_speed_kmh: float = 0.0
    status: VehicleStatus = VehicleStatus.IDLE
    available: bool = True
    route: list[Hashable] = field(default_factory=list)
    route_edge_keys: list[int | str] = field(default_factory=list)
    route_index: int = 0
    capacity: int = 1
    team_assigned: str | None = None
    sector: str = "core"
    base_zone_id: str = "yard"
    current_zone_id: str = "yard"
    route_purpose: str = "idle"
    flow_type: str = "standby"
    sequence_zones: list[str] = field(default_factory=list)
    sequence_index: int = 0
    service_ticks_remaining: int = 0
    progress_on_edge: float = 0.0
    assigned_eta_seconds: float | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    route_geometry: list[tuple[float, float]] = field(default_factory=list)
    rail_only: bool = False


@dataclass
class FieldTeam:
    id: str
    node_id: Hashable
    position: tuple[float, float]
    priority: TeamPriority
    active_request: bool = False
    waiting_time_seconds: float = 0.0
    service_type: str = "inspection"
    sector: str = "yard"
    zone_id: str = "yard"
    role: str = "operations"
    demand_origin_zone: str = "yard"
    demand_destination_zone: str = "yard"
    flow_type: str = "maintenance_patrol"
    assigned_vehicle_id: str | None = None
    last_served_tick: int | None = None


@dataclass
class SimulationEvent:
    id: str
    event_type: str
    edge: tuple[Hashable, Hashable] | None = None
    node_id: str | None = None
    zone_id: str | None = None
    critical_point_id: str | None = None
    severity: float = 1.0
    duration_ticks: int = 10
    remaining_ticks: int = 10
    message: str = ""
    manual: bool = False


@dataclass
class RoutePlan:
    vehicle_id: str
    team_id: str
    path: list[Hashable]
    edge_keys: list[int | str]
    geometry: list[tuple[float, float]]
    distance_m: float
    estimated_time_s: float
    blocked_edges: int
    avg_congestion: float
    edge_count: int
