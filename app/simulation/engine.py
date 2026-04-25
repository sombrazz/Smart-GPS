from __future__ import annotations

import hashlib
import random
import time
from threading import Lock
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Hashable

import pandas as pd

from app.core.settings import EXPORT_DIR
from app.ml.features import build_candidate_feature_row
from app.ml.model_service import ModelService
from app.routing.graph_loader import (
    FLOW_DEFINITIONS,
    PORT_CENTER,
    add_synthetic_rail_corridors,
    annotate_graph_with_operational_context,
    approximate_distance_m,
    build_critical_points,
    build_operational_zones,
    build_operation_sites,
    build_port_graph,
    graph_node_position,
    interpolate_along_coordinates,
)
from app.routing.router import Router
from app.simulation.entities import FieldTeam, SimulationEvent, TeamPriority, Vehicle, VehicleStatus

VEHICLE_BASE_SPEEDS = {
    "train": 34.0,
    "truck": 40.0,
    "pickup": 47.0,
    "support": 42.0,
    "utility": 44.0,
    "crane": 18.0,
}

ROAD_SPEED_PROFILES = {
    "motorway": 46.0,
    "trunk": 42.0,
    "primary": 38.0,
    "secondary": 34.0,
    "tertiary": 31.0,
    "unclassified": 28.0,
    "residential": 24.0,
    "service": 26.0,
    "road": 24.0,
    "living_street": 16.0,
    "rail": 32.0,
}

ROAD_TYPE_MULTIPLIERS = {
    "train": {"rail": 1.0},
    "truck": {"primary": 0.98, "secondary": 0.94, "service": 0.9, "yard": 0.82, "pier": 0.78},
    "pickup": {"primary": 1.06, "secondary": 1.02, "service": 0.95, "yard": 0.88, "pier": 0.82},
    "support": {"primary": 1.0, "secondary": 0.96, "service": 0.92, "yard": 0.84, "pier": 0.8},
    "utility": {"primary": 1.04, "secondary": 1.0, "service": 0.94, "yard": 0.86, "pier": 0.8},
    "crane": {"service": 0.78, "yard": 0.72, "pier": 0.68},
}

OPERATION_SPEED_MULTIPLIERS = {
    "service": 0.93,
    "flow": 1.0,
    "return_to_base": 0.96,
    "idle": 0.85,
}

FLOW_SPEED_MULTIPLIERS = {
    "rail_yard_pier": 0.94,
    "gate_warehouse_pier": 1.0,
    "maintenance_patrol": 0.88,
    "service": 0.92,
    "support": 0.95,
}


class SimulationEngine:
    def __init__(self, seed: int = 7) -> None:
        self.seed = seed
        self.random = random.Random(seed)
        self.tick_seconds = 8
        self.realtime_tick_interval_s = 2.4
        self.ticks_enabled = False
        self.tick_mode_seconds = 10
        self.default_speed_multiplier = 1.0
        self.speed_multiplier = 1.0
        self.base_time = datetime(2026, 4, 13, 8, 0, tzinfo=timezone.utc)
        self.tick = 0
        self.running = False
        self.strategy = "rule"
        self.debug_mode = False
        self.target_vehicle_count = 23
        self.target_team_count = 12
        self.last_comparison: dict[str, Any] | None = None
        self.graph = build_port_graph()
        self.operation_sites = build_operation_sites(self.graph)
        self.graph = add_synthetic_rail_corridors(self.graph, self.operation_sites)
        self.zones = build_operational_zones(self.graph, self.operation_sites)
        self.critical_points = build_critical_points(self.operation_sites)
        self.graph = annotate_graph_with_operational_context(self.graph, self.zones, self.critical_points)
        self.router = Router(self.graph)
        self.model_service = ModelService()
        self.synthetic_records: list[dict[str, Any]] = []
        self.total_route_recalculations = 0
        self.total_completed_services = 0
        self.total_travel_time_s = 0.0
        self.total_response_time_s = 0.0
        self.events: dict[str, SimulationEvent] = {}
        self.vehicles: dict[str, Vehicle] = {}
        self.teams: dict[str, FieldTeam] = {}
        self.zone_vehicle_density: dict[str, int] = {zone_id: 0 for zone_id in self.zones}
        self.zone_team_density: dict[str, int] = {zone_id: 0 for zone_id in self.zones}
        self.zone_active_requests: dict[str, int] = {zone_id: 0 for zone_id in self.zones}
        self.dominant_flow = "rail_yard_pier"
        self._tick_lock = Lock()
        self._last_runtime_sync = time.monotonic()
        self._setup_entities()
        self._refresh_operational_snapshot()

    def _site(self, site_id: str) -> dict[str, Any]:
        return self.operation_sites[site_id]

    def _current_hour(self) -> int:
        sim_time = self.base_time + timedelta(seconds=self.tick * self.tick_seconds)
        return sim_time.hour

    def _flow_weights(self) -> dict[str, float]:
        hour = self._current_hour()
        return {
            "rail_yard_pier": 1.1 if 7 <= hour <= 18 else 0.65,
            "gate_warehouse_pier": 1.25 if 6 <= hour <= 10 else 0.85 if 11 <= hour <= 17 else 0.55,
            "maintenance_patrol": 0.95 if 8 <= hour <= 17 else 0.45,
        }

    def _pick_weighted_flow(self) -> str:
        weighted = self._flow_weights()
        self.dominant_flow = max(weighted, key=weighted.get)
        return self.random.choices(list(weighted.keys()), weights=list(weighted.values()), k=1)[0]

    def _pick_zone_node(self, zone_id: str, index_seed: int = 0) -> Hashable:
        zone_nodes = self.zones[zone_id]["node_ids"]
        return zone_nodes[(index_seed + self.random.randint(0, len(zone_nodes) - 1)) % len(zone_nodes)]

    def _pick_zone_position(self, zone_id: str, index_seed: int = 0) -> tuple[Hashable, tuple[float, float]]:
        node_id = self._pick_zone_node(zone_id, index_seed)
        return node_id, self.node_pos(node_id)

    def _pick_vehicle_zone_node(self, zone_id: str, *, rail_only: bool = False, index_seed: int = 0) -> Hashable:
        if rail_only:
            rail_site_by_zone = {
                "rail": "rail_arrival",
                "yard": "yard_central",
                "pier": "pier_access",
            }
            site_id = rail_site_by_zone.get(zone_id)
            rail_nodes = self.graph.graph.get("rail_site_nodes", {})
            if site_id and site_id in rail_nodes:
                return rail_nodes[site_id]
        return self._pick_zone_node(zone_id, index_seed)

    def _assign_vehicle_sequence(self, vehicle_type: str, index: int) -> tuple[str, list[str]]:
        if vehicle_type == "train":
            return ("rail", ["rail", "yard", "pier", "rail"])
        if vehicle_type == "truck":
            return ("rail" if index % 2 == 0 else "yard", ["rail", "yard", "pier", "yard"])
        if vehicle_type == "crane":
            return ("pier" if index % 2 == 0 else "yard", ["pier", "yard", "pier"])
        if vehicle_type == "utility":
            return ("maintenance", ["maintenance", "yard", "crossroads", "maintenance"])
        if vehicle_type == "support":
            support_bases = ["gate", "yard", "crossroads"]
            return (support_bases[index % len(support_bases)], ["gate", "crossroads", "yard", "gate"])
        return ("yard" if index % 2 == 0 else "rail", ["gate", "warehouse", "pier", "gate"])

    def _assign_team_profile(self, index: int) -> tuple[str, str, TeamPriority, str]:
        profiles = [
            ("maintenance", "yard", TeamPriority.MEDIUM, "maintenance_patrol"),
            ("maintenance", "maintenance", TeamPriority.HIGH, "maintenance_patrol"),
            ("operations", "pier", TeamPriority.HIGH, "rail_yard_pier"),
            ("operations", "rail", TeamPriority.MEDIUM, "rail_yard_pier"),
            ("control", "gate", TeamPriority.HIGH, "gate_warehouse_pier"),
            ("control", "crossroads", TeamPriority.MEDIUM, "gate_warehouse_pier"),
            ("operations", "yard", TeamPriority.LOW, "rail_yard_pier"),
        ]
        return profiles[index % len(profiles)]

    def _setup_entities(self) -> None:
        vehicle_types = (
            [("train", VEHICLE_BASE_SPEEDS["train"], 24)] * 5
            + [("truck", VEHICLE_BASE_SPEEDS["truck"], 8)] * 6
            + [("pickup", VEHICLE_BASE_SPEEDS["pickup"], 4)] * 4
            + [("support", VEHICLE_BASE_SPEEDS["support"], 3)] * 3
            + [("utility", VEHICLE_BASE_SPEEDS["utility"], 2)] * 3
            + [("crane", VEHICLE_BASE_SPEEDS["crane"], 12)] * 2
        )

        self.vehicles = {}
        for index in range(self.target_vehicle_count):
            vehicle_type, speed_kmh, capacity = vehicle_types[index % len(vehicle_types)]
            base_zone_id, sequence = self._assign_vehicle_sequence(vehicle_type, index)
            vehicle_id = f"V-{index + 1:02d}"
            self.vehicles[vehicle_id] = self._vehicle(
                vehicle_id=vehicle_id,
                vehicle_type=vehicle_type,
                base_zone_id=base_zone_id,
                sequence_zones=sequence,
                speed_kmh=speed_kmh,
                capacity=capacity,
                index=index,
            )

        self.teams = {}
        for index in range(self.target_team_count):
            role, zone_id, priority, flow_type = self._assign_team_profile(index)
            team_id = f"T-{index + 1:02d}"
            self.teams[team_id] = self._team(team_id, zone_id, role, priority, flow_type, index)

    def _vehicle(
        self,
        vehicle_id: str,
        vehicle_type: str,
        base_zone_id: str,
        sequence_zones: list[str],
        speed_kmh: float,
        capacity: int,
        index: int,
    ) -> Vehicle:
        rail_only = vehicle_type == "train"
        node_id = self._pick_vehicle_zone_node(base_zone_id, rail_only=rail_only, index_seed=index)
        position = self.node_pos(node_id)
        return Vehicle(
            id=vehicle_id,
            vehicle_type=vehicle_type,
            current_node=node_id,
            position=position,
            speed_kmh=speed_kmh,
            current_speed_kmh=0.0,
            sector=self.zones[base_zone_id]["kind"],
            capacity=capacity,
            base_zone_id=base_zone_id,
            current_zone_id=base_zone_id,
            sequence_zones=sequence_zones,
            sequence_index=0,
            rail_only=rail_only,
        )

    def _team(
        self,
        team_id: str,
        zone_id: str,
        role: str,
        priority: TeamPriority,
        flow_type: str,
        index: int,
    ) -> FieldTeam:
        node_id, position = self._pick_zone_position(zone_id, index * 2 + 3)
        service_type = {
            "maintenance": "inspection",
            "operations": "logistics",
            "control": "safety",
        }.get(role, "support")
        return FieldTeam(
            id=team_id,
            node_id=node_id,
            position=position,
            priority=priority,
            active_request=False,
            service_type=service_type,
            sector=self.zones[zone_id]["kind"],
            zone_id=zone_id,
            role=role,
            demand_origin_zone=zone_id,
            demand_destination_zone=zone_id,
            flow_type=flow_type,
        )

    def reset(self) -> None:
        self.tick = 0
        self.running = False
        self._last_runtime_sync = time.monotonic()
        self.tick_seconds = self.tick_mode_seconds if self.ticks_enabled else 8
        self.speed_multiplier = self.default_speed_multiplier
        self.synthetic_records = []
        self.total_route_recalculations = 0
        self.total_completed_services = 0
        self.total_travel_time_s = 0.0
        self.total_response_time_s = 0.0
        self.last_comparison = None
        self.events = {}
        self.graph = build_port_graph()
        self.operation_sites = build_operation_sites(self.graph)
        self.graph = add_synthetic_rail_corridors(self.graph, self.operation_sites)
        self.zones = build_operational_zones(self.graph, self.operation_sites)
        self.critical_points = build_critical_points(self.operation_sites)
        self.graph = annotate_graph_with_operational_context(self.graph, self.zones, self.critical_points)
        self.router = Router(self.graph)
        self._setup_entities()
        self._refresh_operational_snapshot()

    def node_pos(self, node_id: Hashable) -> tuple[float, float]:
        return graph_node_position(self.graph, node_id)

    def _infer_zone_from_node(self, node_id: Hashable) -> str:
        node_str = str(node_id)
        if node_str.startswith("rail::"):
            if "pier" in node_str:
                return "pier"
            if "yard" in node_str:
                return "yard"
            return "rail"
        pos = self.node_pos(node_id)
        return min(
            self.zones,
            key=lambda candidate: approximate_distance_m(pos, self.zones[candidate]["center"]),
        )

    def _refresh_operational_snapshot(self) -> None:
        self.zone_vehicle_density = {zone_id: 0 for zone_id in self.zones}
        self.zone_team_density = {zone_id: 0 for zone_id in self.zones}
        self.zone_active_requests = {zone_id: 0 for zone_id in self.zones}

        for vehicle in self.vehicles.values():
            vehicle.current_zone_id = self._infer_zone_from_node(vehicle.current_node)
            self.zone_vehicle_density[vehicle.current_zone_id] += 1

        for team in self.teams.values():
            self.zone_team_density[team.zone_id] += 1
            if team.active_request:
                self.zone_active_requests[team.zone_id] += 1

        self.dominant_flow = max(self._flow_weights(), key=self._flow_weights().get)

    def start(self) -> None:
        self._sync_runtime()
        self.running = True
        self._last_runtime_sync = time.monotonic()
        self._prime_operational_state()

    def pause(self) -> None:
        self._sync_runtime()
        self.running = False

    def set_speed(self, multiplier: float) -> None:
        self.speed_multiplier = max(0.25, min(multiplier, 8.0))

    def configure_runtime(self, *, ticks_enabled: bool, tick_seconds: int | None = None) -> None:
        self.ticks_enabled = ticks_enabled
        if tick_seconds is not None:
            self.tick_mode_seconds = max(5, min(int(tick_seconds), 60))
        self.tick_seconds = self.tick_mode_seconds if self.ticks_enabled else 8
        self._last_runtime_sync = time.monotonic()

    def set_strategy(self, strategy: str) -> None:
        if strategy in {"rule", "ml"}:
            self.strategy = strategy

    def set_debug_mode(self, enabled: bool) -> None:
        self.debug_mode = enabled

    def configure_scenario(self, vehicle_count: int, team_count: int) -> dict[str, Any]:
        self.target_vehicle_count = max(1, min(vehicle_count, 60))
        self.target_team_count = max(1, min(team_count, 120))
        self.reset()
        return self.get_state()

    def simulation_timestamp(self) -> str:
        sim_time = self.base_time + timedelta(seconds=self.tick * self.tick_seconds)
        return sim_time.isoformat()

    def _vehicle_allowed_edge_types(self, vehicle: Vehicle) -> set[str] | None:
        return {"rail"} if vehicle.rail_only else None

    def _service_capable_vehicle_ids(self) -> list[str]:
        return [
            vehicle.id
            for vehicle in self.vehicles.values()
            if vehicle.vehicle_type not in {"train", "crane"}
        ]

    def _prime_operational_state(self) -> None:
        if any(vehicle.route for vehicle in self.vehicles.values()):
            return
        for _ in range(3):
            self._refresh_operational_snapshot()
            self._spawn_zone_based_requests()
            self._dispatch_requests()
            self._dispatch_operational_flows()
        self._refresh_operational_snapshot()

    def _step_once(self) -> None:
        self.tick += 1
        self._refresh_operational_snapshot()
        self._update_team_waiting_times()
        self._update_events()
        self._advance_vehicle_service_states()
        self._spawn_zone_based_requests()
        self._spawn_critical_events()
        self._dispatch_requests()
        self._dispatch_operational_flows()
        self._move_vehicles()
        self._refresh_operational_snapshot()

    def _sync_runtime(self) -> None:
        if not self.running:
            self._last_runtime_sync = time.monotonic()
            return
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_runtime_sync)
        interval_s = float(self.tick_mode_seconds) if self.ticks_enabled else self.realtime_tick_interval_s
        pending_steps = min(12, int(elapsed / max(interval_s, 0.2)))
        if pending_steps <= 0:
            return
        with self._tick_lock:
            for _ in range(pending_steps):
                self._step_once()
            self._last_runtime_sync += pending_steps * interval_s

    def step(self, count: int = 1) -> dict[str, Any]:
        with self._tick_lock:
            for _ in range(count):
                self._step_once()
        self._last_runtime_sync = time.monotonic()
        return self.get_state()

    def _update_team_waiting_times(self) -> None:
        for team in self.teams.values():
            if team.active_request:
                team.waiting_time_seconds += self.tick_seconds

    def _update_events(self) -> None:
        expired: list[str] = []
        for event_id, event in self.events.items():
            event.remaining_ticks -= 1
            if event.remaining_ticks <= 0:
                self._clear_event_effects(event)
                expired.append(event_id)
        for event_id in expired:
            del self.events[event_id]

    def _pick_team_for_flow(self, flow_id: str) -> FieldTeam | None:
        flow = FLOW_DEFINITIONS[flow_id]
        eligible = [
            team
            for team in self.teams.values()
            if not team.active_request and team.zone_id in flow["request_zones"]
        ]
        if not eligible:
            return None
        return self.random.choice(eligible)

    def _activate_team_request(self, team: FieldTeam, flow_id: str) -> None:
        flow = FLOW_DEFINITIONS[flow_id]
        priority_map = {
            "low": TeamPriority.LOW,
            "medium": TeamPriority.MEDIUM,
            "high": TeamPriority.HIGH,
            "critical": TeamPriority.CRITICAL,
        }
        team.active_request = True
        team.assigned_vehicle_id = None
        team.waiting_time_seconds = 0.0
        team.flow_type = flow_id
        team.priority = priority_map[flow["priority"]]
        if flow_id == "rail_yard_pier":
            team.demand_origin_zone = "rail"
            team.demand_destination_zone = "yard" if team.zone_id == "yard" else "pier"
            team.service_type = "bulk_transfer"
        elif flow_id == "gate_warehouse_pier":
            team.demand_origin_zone = "gate"
            team.demand_destination_zone = "warehouse" if team.zone_id == "warehouse" else "pier"
            team.service_type = "cargo_gate"
        else:
            team.demand_origin_zone = "maintenance"
            team.demand_destination_zone = team.zone_id
            team.service_type = "maintenance"

    def _spawn_zone_based_requests(self) -> None:
        active_requests = sum(1 for team in self.teams.values() if team.active_request)
        if active_requests > max(3, self.target_team_count // 3):
            return
        spawn_budget = 1 if self.tick % 2 else 2
        for _ in range(spawn_budget):
            flow_id = self._pick_weighted_flow()
            team = self._pick_team_for_flow(flow_id)
            if team is None:
                continue
            self._activate_team_request(team, flow_id)

    def _spawn_critical_events(self) -> None:
        if self.tick % 5 != 0 or len(self.events) >= 5:
            return
        flow_weight = self._flow_weights()[self.dominant_flow]
        if self.random.random() > min(0.9, 0.25 + flow_weight * 0.22):
            return

        point = self.random.choices(
            list(self.critical_points.values()),
            weights=[point["weight"] for point in self.critical_points.values()],
            k=1,
        )[0]
        candidate_edges = [
            (u, v, edge_key, data)
            for u, v, edge_key, data in self.graph.edges(keys=True, data=True)
            if point["id"] in data.get("critical_point_ids", [])
        ]
        if not candidate_edges:
            return
        u, v, edge_key, edge_data = self.random.choice(candidate_edges)
        event_type = self.random.choices(
            ["block", "congestion", "slowdown"],
            weights=[0.18, 0.54, 0.28],
            k=1,
        )[0]
        severity = round(min(1.0, 0.45 + point["weight"] * self.random.uniform(0.2, 0.55)), 2)
        duration = self.random.randint(6, 16)
        event = self.create_event(
            event_type=event_type,
            edge=(u, v),
            edge_key=edge_key,
            severity=severity,
            duration_ticks=duration,
        )
        event.zone_id = point["zone_id"]
        event.critical_point_id = point["id"]
        event.node_id = str(point["node_id"])
        event.message = f"{event_type} em {point['label']}"
        edge_data["congestion"] = min(0.95, edge_data["congestion"] + 0.06)

    def _dispatch_requests(self) -> None:
        for team in self.teams.values():
            if not team.active_request or team.assigned_vehicle_id:
                continue
            chosen = self._choose_vehicle_for_team(team)
            if not chosen:
                continue
            vehicle = self.vehicles[chosen["vehicle_id"]]
            route_plan = self.router.shortest_path(
                vehicle.current_node,
                team.node_id,
                vehicle_speed_kmh=vehicle.speed_kmh,
                allowed_road_types=self._vehicle_allowed_edge_types(vehicle),
                origin_zone=vehicle.current_zone_id,
                target_zone=team.zone_id,
                flow_type=team.flow_type,
                dominant_flow=self.dominant_flow,
            )
            if route_plan is None:
                continue
            self._assign_route(
                vehicle=vehicle,
                team=team,
                path=route_plan.path,
                edge_keys=route_plan.edge_keys,
                geometry=route_plan.geometry,
                eta_seconds=route_plan.estimated_time_s,
                route_purpose="service",
                flow_type=team.flow_type,
            )

    def _flow_for_vehicle(self, vehicle: Vehicle) -> str:
        for flow_id, flow in FLOW_DEFINITIONS.items():
            if vehicle.vehicle_type in flow["vehicle_types"] and vehicle.base_zone_id in flow["sequence"]:
                return flow_id
        return "maintenance_patrol"

    def _dispatch_operational_flows(self) -> None:
        for vehicle in self.vehicles.values():
            if not vehicle.available or vehicle.status != VehicleStatus.IDLE or not vehicle.sequence_zones:
                continue
            dispatch_chance = 0.82 if vehicle.vehicle_type == "train" else 0.62 if vehicle.vehicle_type == "truck" else 0.46
            if self.random.random() > dispatch_chance:
                continue
            next_zone_index = (vehicle.sequence_index + 1) % len(vehicle.sequence_zones)
            target_zone = vehicle.sequence_zones[next_zone_index]
            target_node = self._pick_vehicle_zone_node(
                target_zone,
                rail_only=vehicle.rail_only,
                index_seed=vehicle.sequence_index + self.tick,
            )
            if target_node == vehicle.current_node:
                vehicle.sequence_index = next_zone_index
                continue
            flow_type = self._flow_for_vehicle(vehicle)
            route_plan = self.router.shortest_path(
                vehicle.current_node,
                target_node,
                vehicle_speed_kmh=vehicle.speed_kmh,
                allowed_road_types=self._vehicle_allowed_edge_types(vehicle),
                origin_zone=vehicle.current_zone_id,
                target_zone=target_zone,
                flow_type=flow_type,
                dominant_flow=self.dominant_flow,
            )
            if route_plan is None:
                continue
            vehicle.sequence_index = next_zone_index
            self._assign_route(
                vehicle=vehicle,
                team=None,
                path=route_plan.path,
                edge_keys=route_plan.edge_keys,
                geometry=route_plan.geometry,
                eta_seconds=route_plan.estimated_time_s,
                route_purpose="flow",
                flow_type=flow_type,
            )

    def _estimate_observed_response_time(self, team: FieldTeam, vehicle: Vehicle, eval_row: dict[str, Any]) -> float:
        vehicle_speed_factor = max(0.75, 30.0 / max(vehicle.speed_kmh, 8.0))
        stochastic_factor = 1.0 + self.random.uniform(0.03, 0.15)
        density_penalty = 1.0 + (self.zone_vehicle_density.get(team.zone_id, 0) * 0.025)
        route_penalty = 1.0 + eval_row["avg_congestion"] * 0.35 + eval_row["blocked_edges"] * 0.15
        critical_penalty = 1.0 + eval_row.get("criticality_score", 0.0) * 0.2
        observed_travel = eval_row["estimated_time_s"] * vehicle_speed_factor * route_penalty * stochastic_factor * density_penalty * critical_penalty
        return observed_travel + team.waiting_time_seconds

    def _build_candidate_rows(self, team: FieldTeam, evaluations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not evaluations:
            return []
        observed_rows: list[tuple[dict[str, Any], float]] = []
        for eval_row in evaluations:
            vehicle = self.vehicles[eval_row["vehicle_id"]]
            observed_response = self._estimate_observed_response_time(team, vehicle, eval_row)
            observed_rows.append((eval_row, observed_response))

        best_vehicle_id = min(observed_rows, key=lambda item: item[1])[0]["vehicle_id"]
        timestamp = self.simulation_timestamp()
        candidate_rows: list[dict[str, Any]] = []
        for eval_row, observed_response in observed_rows:
            vehicle = self.vehicles[eval_row["vehicle_id"]]
            observed_travel_time_s = max(0.0, observed_response - team.waiting_time_seconds)
            feature_row = build_candidate_feature_row(
                timestamp=timestamp,
                team=team,
                vehicle=vehicle,
                route_metrics=eval_row,
                observed_time_s=observed_travel_time_s,
                is_best_vehicle=(vehicle.id == best_vehicle_id),
                origin_zone_density=self.zone_vehicle_density.get(eval_row["origin_zone"], 0),
                destination_zone_density=self.zone_vehicle_density.get(team.zone_id, 0),
            )
            candidate_rows.append(feature_row)
            self.synthetic_records.append(feature_row)
        return candidate_rows

    def _choose_vehicle_for_team(self, team: FieldTeam) -> dict[str, Any] | None:
        evaluations = self.router.evaluate_vehicle_options(
            vehicle_ids=self._service_capable_vehicle_ids(),
            vehicle_node_lookup={vehicle.id: vehicle.current_node for vehicle in self.vehicles.values()},
            team_id=team.id,
            team_node=team.node_id,
            priorities={team.id: team.priority.value},
            available_lookup={vehicle.id: vehicle.available for vehicle in self.vehicles.values()},
            vehicle_speed_lookup={vehicle.id: vehicle.speed_kmh for vehicle in self.vehicles.values()},
            vehicle_edge_type_lookup={vehicle.id: self._vehicle_allowed_edge_types(vehicle) for vehicle in self.vehicles.values()},
            vehicle_zone_lookup={vehicle.id: vehicle.current_zone_id for vehicle in self.vehicles.values()},
            team_zone=team.zone_id,
            flow_type=team.flow_type,
            dominant_flow=self.dominant_flow,
        )
        if not evaluations:
            return None

        for eval_row in evaluations:
            priority_weight = {
                "low": 1.0,
                "medium": 0.95,
                "high": 0.9,
                "critical": 0.82,
            }.get(team.priority.value, 1.0)
            eval_row["priority_weighted_eta_s"] = eval_row["estimated_time_s"] * priority_weight
            eval_row["criticality_score"] = round(
                eval_row["avg_congestion"] * 0.45
                + (self.zone_vehicle_density.get(team.zone_id, 0) * 0.03)
                + (self.zone_active_requests.get(team.zone_id, 0) * 0.05),
                3,
            )

        candidate_rows = self._build_candidate_rows(team, evaluations)
        if self.strategy == "ml":
            prediction = self.model_service.predict_best_vehicle(candidate_rows)
            if prediction:
                return next(row for row in evaluations if row["vehicle_id"] == prediction["vehicle_id"])
        return min(
            evaluations,
            key=lambda row: row["priority_weighted_eta_s"]
            + row["avg_congestion"] * 130.0
            + row["criticality_score"] * 90.0
            + abs(self.zone_vehicle_density.get(row["origin_zone"], 0) - self.zone_vehicle_density.get(team.zone_id, 0)) * 4.0,
        )

    def _assign_route(
        self,
        vehicle: Vehicle,
        team: FieldTeam | None,
        path: list[Hashable],
        edge_keys: list[int | str],
        geometry: list[tuple[float, float]],
        eta_seconds: float,
        route_purpose: str,
        flow_type: str,
    ) -> None:
        vehicle.route = path
        vehicle.route_edge_keys = edge_keys
        vehicle.route_index = 0
        vehicle.progress_on_edge = 0.0
        vehicle.status = VehicleStatus.EN_ROUTE if route_purpose == "service" else VehicleStatus.RETURNING
        vehicle.available = False
        vehicle.team_assigned = team.id if team else None
        vehicle.assigned_eta_seconds = eta_seconds
        vehicle.route_geometry = geometry
        vehicle.position = self.node_pos(path[0])
        vehicle.current_speed_kmh = 0.0
        vehicle.route_purpose = route_purpose
        vehicle.flow_type = flow_type
        if team:
            team.assigned_vehicle_id = vehicle.id
        self.total_route_recalculations += 1

    def _move_vehicles(self) -> None:
        for vehicle in self.vehicles.values():
            if vehicle.status not in {VehicleStatus.EN_ROUTE, VehicleStatus.RETURNING} or len(vehicle.route) < 2:
                vehicle.current_speed_kmh = 0.0
                continue
            origin = vehicle.route[vehicle.route_index]
            target = vehicle.route[vehicle.route_index + 1]
            edge_key = vehicle.route_edge_keys[vehicle.route_index]
            edge = self.graph[origin][target][edge_key]
            target_speed_kmh = self._target_vehicle_speed(vehicle, edge)
            smoothing = 0.42 if vehicle.current_speed_kmh > 0 else 0.7
            effective_speed_kmh = vehicle.current_speed_kmh + (target_speed_kmh - vehicle.current_speed_kmh) * smoothing
            floor_speed = 12.0 if vehicle.vehicle_type == "train" else 7.0 if vehicle.vehicle_type == "truck" else 5.0
            effective_speed_kmh = max(floor_speed, effective_speed_kmh) if target_speed_kmh > floor_speed else max(0.0, effective_speed_kmh)
            vehicle.current_speed_kmh = round(effective_speed_kmh, 1)
            step_distance = vehicle.current_speed_kmh * 1000 / 3600 * self.tick_seconds * self.speed_multiplier
            vehicle.progress_on_edge += step_distance
            edge_distance = max(edge["distance_m"], 1.0)

            if vehicle.progress_on_edge >= edge_distance:
                vehicle.current_node = target
                vehicle.position = self.node_pos(target)
                vehicle.progress_on_edge = 0.0
                vehicle.route_index += 1
                if vehicle.route_index >= len(vehicle.route) - 1:
                    self._complete_vehicle_route(vehicle)
                    continue

            vehicle.position = interpolate_along_coordinates(edge["geometry_coords"], vehicle.progress_on_edge)
            if edge.get("operational_zone") in self.zones:
                vehicle.current_zone_id = edge["operational_zone"]

    def _target_vehicle_speed(self, vehicle: Vehicle, edge: dict[str, Any]) -> float:
        road_type = edge.get("road_type", "service")
        zone_kind = edge.get("operational_zone") or vehicle.current_zone_id
        profile_limit = ROAD_SPEED_PROFILES.get(road_type, 26.0)
        if zone_kind in {"yard", "pier", "gate", "crossroads", "maintenance", "rail"}:
            profile_limit = min(profile_limit, ROAD_SPEED_PROFILES.get(zone_kind if zone_kind == "rail" else "service", profile_limit))

        edge_limit = max(float(edge.get("speed_kmh", profile_limit)), profile_limit)
        vehicle_base = VEHICLE_BASE_SPEEDS.get(vehicle.vehicle_type, vehicle.speed_kmh)
        road_multiplier = ROAD_TYPE_MULTIPLIERS.get(vehicle.vehicle_type, {}).get(road_type, 1.0)
        if zone_kind in {"yard", "pier"}:
            road_multiplier *= ROAD_TYPE_MULTIPLIERS.get(vehicle.vehicle_type, {}).get(zone_kind, 0.84)
        elif zone_kind in {"gate", "crossroads", "maintenance"}:
            road_multiplier *= 0.86

        operation_multiplier = OPERATION_SPEED_MULTIPLIERS.get(vehicle.route_purpose, 0.95)
        flow_multiplier = FLOW_SPEED_MULTIPLIERS.get(vehicle.flow_type, 0.96)

        congestion = max(0.0, min(float(edge.get("congestion", 0.0)), 0.95))
        congestion_multiplier = 1.0 - (congestion * 0.58)

        zone_density = self.zone_vehicle_density.get(vehicle.current_zone_id, 0)
        density_multiplier = max(0.62, 1.0 - (max(zone_density - 2, 0) * 0.035))

        criticality = float(edge.get("criticality", 0.0))
        critical_multiplier = max(0.72, 1.0 - criticality * 0.24)
        if edge.get("blocked"):
            critical_multiplier *= 0.42

        remaining_on_edge = max(0.0, float(edge.get("distance_m", 0.0)) - vehicle.progress_on_edge)
        approach_multiplier = 1.0
        if remaining_on_edge < 70:
            approach_multiplier *= 0.84
        if remaining_on_edge < 35:
            approach_multiplier *= 0.8
        if vehicle.route_index >= len(vehicle.route) - 2:
            approach_multiplier *= 0.88

        variance = 1.0 + self.random.uniform(-0.04, 0.08)

        target_speed = min(vehicle_base, edge_limit) * road_multiplier
        target_speed *= operation_multiplier * flow_multiplier * congestion_multiplier * density_multiplier * critical_multiplier * approach_multiplier * variance

        min_operational_speed = 14.0 if vehicle.vehicle_type == "train" else 8.0 if vehicle.vehicle_type == "truck" else 6.0
        target_speed = max(min_operational_speed * min(congestion_multiplier, 1.0), target_speed)
        return round(min(target_speed, vehicle_base * 1.02, edge_limit * 1.05), 1)

    def _complete_vehicle_route(self, vehicle: Vehicle) -> None:
        vehicle.current_zone_id = self._infer_zone_from_node(vehicle.current_node)
        if vehicle.route_purpose == "service" and vehicle.team_assigned:
            self._complete_vehicle_assignment(vehicle)
            return

        vehicle.service_ticks_remaining = self.random.randint(1, 3)
        vehicle.status = VehicleStatus.ASSISTING
        vehicle.available = False
        vehicle.current_speed_kmh = 0.0
        vehicle.route = []
        vehicle.route_edge_keys = []
        vehicle.route_geometry = []
        vehicle.route_index = 0
        vehicle.progress_on_edge = 0.0

    def _complete_vehicle_assignment(self, vehicle: Vehicle) -> None:
        if not vehicle.team_assigned:
            return
        team = self.teams[vehicle.team_assigned]
        observed_travel_time_s = (vehicle.assigned_eta_seconds or 0.0) * (1.0 + self.random.uniform(0.03, 0.18))
        self.total_travel_time_s += observed_travel_time_s
        self.total_response_time_s += observed_travel_time_s + team.waiting_time_seconds
        self.total_completed_services += 1
        team.active_request = False
        team.waiting_time_seconds = 0.0
        team.assigned_vehicle_id = None
        team.last_served_tick = self.tick
        vehicle.history.append(
            {
                "tick": self.tick,
                "team_id": team.id,
                "path": [str(node_id) for node_id in vehicle.route],
                "edge_keys": [str(edge_key) for edge_key in vehicle.route_edge_keys],
                "observed_travel_time_s": observed_travel_time_s,
                "flow_type": team.flow_type,
                "team_zone": team.zone_id,
            }
        )
        vehicle.route = []
        vehicle.route_edge_keys = []
        vehicle.route_geometry = []
        vehicle.route_index = 0
        vehicle.service_ticks_remaining = self.random.randint(1, 2)
        vehicle.assigned_eta_seconds = None
        vehicle.status = VehicleStatus.ASSISTING
        vehicle.available = False
        vehicle.route_purpose = "return_to_base"
        vehicle.team_assigned = None

    def _advance_vehicle_service_states(self) -> None:
        for vehicle in self.vehicles.values():
            if vehicle.status != VehicleStatus.ASSISTING:
                continue
            vehicle.service_ticks_remaining = max(0, vehicle.service_ticks_remaining - 1)
            if vehicle.service_ticks_remaining > 0:
                continue
            if vehicle.route_purpose == "return_to_base":
                self._send_vehicle_to_zone(vehicle, vehicle.base_zone_id, vehicle.flow_type)
            else:
                vehicle.status = VehicleStatus.IDLE
                vehicle.available = True
                vehicle.current_speed_kmh = 0.0
                vehicle.route_purpose = "idle"

    def _send_vehicle_to_zone(self, vehicle: Vehicle, zone_id: str, flow_type: str) -> None:
        target_node = self._pick_vehicle_zone_node(
            zone_id,
            rail_only=vehicle.rail_only,
            index_seed=self.tick + vehicle.sequence_index,
        )
        if target_node == vehicle.current_node:
            vehicle.status = VehicleStatus.IDLE
            vehicle.available = True
            vehicle.current_speed_kmh = 0.0
            vehicle.route_purpose = "idle"
            vehicle.current_zone_id = zone_id
            return
        route_plan = self.router.shortest_path(
            vehicle.current_node,
            target_node,
            vehicle_speed_kmh=vehicle.speed_kmh,
            allowed_road_types=self._vehicle_allowed_edge_types(vehicle),
            origin_zone=vehicle.current_zone_id,
            target_zone=zone_id,
            flow_type=flow_type,
            dominant_flow=self.dominant_flow,
        )
        if route_plan is None:
            vehicle.status = VehicleStatus.IDLE
            vehicle.available = True
            vehicle.current_speed_kmh = 0.0
            vehicle.route_purpose = "idle"
            return
        self._assign_route(
            vehicle=vehicle,
            team=None,
            path=route_plan.path,
            edge_keys=route_plan.edge_keys,
            geometry=route_plan.geometry,
            eta_seconds=route_plan.estimated_time_s,
            route_purpose="flow",
            flow_type=flow_type,
        )
        vehicle.status = VehicleStatus.RETURNING

    def create_event(
        self,
        *,
        event_type: str,
        edge: tuple[Hashable, Hashable] | None,
        edge_key: int | str | None = None,
        severity: float = 1.0,
        duration_ticks: int = 10,
        manual: bool = False,
    ) -> SimulationEvent:
        event_id = f"E-{len(self.events) + 1:03d}"
        event = SimulationEvent(
            id=event_id,
            event_type=event_type,
            edge=edge,
            severity=severity,
            duration_ticks=duration_ticks,
            remaining_ticks=duration_ticks,
            message=f"{event_type} on {edge}",
            manual=manual,
        )
        event.edge_key = edge_key
        self.events[event_id] = event
        self._apply_event_effects(event)
        return event

    def _resolve_event_edge_key(self, u: Hashable, v: Hashable, edge_key: int | str | None) -> int | str:
        edge_bundle = self.graph.get_edge_data(u, v)
        if edge_bundle is None:
            raise KeyError(f"Edge {(u, v)} not found")
        if edge_key is not None and edge_key in edge_bundle:
            return edge_key
        return min(edge_bundle, key=lambda key: edge_bundle[key]["distance_m"])

    def _apply_event_effects(self, event: SimulationEvent) -> None:
        if not event.edge:
            return
        u, v = event.edge
        edge_key = self._resolve_event_edge_key(u, v, getattr(event, "edge_key", None))
        event.edge_key = edge_key
        data = self.graph[u][v][edge_key]
        event._original_edge_state = {
            "blocked": data["blocked"],
            "congestion": data["congestion"],
            "speed_kmh": data["speed_kmh"],
        }
        event.zone_id = data.get("operational_zone")
        critical_ids = data.get("critical_point_ids", [])
        if critical_ids:
            event.critical_point_id = critical_ids[0]
        if event.event_type == "block":
            data["blocked"] = True
        elif event.event_type == "congestion":
            data["congestion"] = min(0.95, data["congestion"] + 0.35 * event.severity)
        elif event.event_type == "slowdown":
            data["speed_kmh"] = max(6.0, data["speed_kmh"] * (1.0 - 0.35 * event.severity))
        self._reroute_impacted_vehicles((u, v), edge_key)

    def _clear_event_effects(self, event: SimulationEvent) -> None:
        if not event.edge or not hasattr(event, "_original_edge_state"):
            return
        u, v = event.edge
        edge_key = getattr(event, "edge_key", None)
        if edge_key is None or edge_key not in self.graph[u][v]:
            return
        self.graph[u][v][edge_key].update(event._original_edge_state)

    def create_manual_request(self, team_id: str | None = None) -> FieldTeam:
        team = self.teams[team_id] if team_id and team_id in self.teams else self.random.choice(list(self.teams.values()))
        flow_id = self._pick_weighted_flow()
        self._activate_team_request(team, flow_id)
        return team

    def _reroute_impacted_vehicles(self, edge: tuple[Hashable, Hashable], edge_key: int | str) -> None:
        impacted_ref = (edge[0], edge[1], edge_key)
        for vehicle in self.vehicles.values():
            if vehicle.status not in {VehicleStatus.EN_ROUTE, VehicleStatus.RETURNING}:
                continue
            remaining_refs = list(zip(vehicle.route[vehicle.route_index:], vehicle.route[vehicle.route_index + 1 :], vehicle.route_edge_keys[vehicle.route_index:]))
            if impacted_ref not in remaining_refs:
                continue

            if vehicle.team_assigned:
                target_node = self.teams[vehicle.team_assigned].node_id
                target_zone = self.teams[vehicle.team_assigned].zone_id
            else:
                target_zone = vehicle.sequence_zones[vehicle.sequence_index] if vehicle.sequence_zones else vehicle.base_zone_id
                target_node = self._pick_zone_node(target_zone, self.tick)

            replanned = self.router.shortest_path(
                vehicle.current_node,
                target_node,
                vehicle_speed_kmh=vehicle.speed_kmh,
                origin_zone=vehicle.current_zone_id,
                target_zone=target_zone,
                flow_type=vehicle.flow_type,
                dominant_flow=self.dominant_flow,
            )
            if replanned is None:
                continue
            vehicle.route = replanned.path
            vehicle.route_edge_keys = replanned.edge_keys
            vehicle.route_index = 0
            vehicle.progress_on_edge = 0.0
            vehicle.route_geometry = replanned.geometry
            vehicle.assigned_eta_seconds = replanned.estimated_time_s
            self.total_route_recalculations += 1

    def export_dataset(self, file_format: str = "csv") -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        if not self.synthetic_records:
            self.generate_synthetic_scenarios(200)
        frame = pd.DataFrame(self.synthetic_records)
        if file_format == "json":
            path = EXPORT_DIR / f"synthetic_dataset_{timestamp}.json"
            frame.to_json(path, orient="records", indent=2)
            return path
        path = EXPORT_DIR / f"synthetic_dataset_{timestamp}.csv"
        frame.to_csv(path, index=False)
        return path

    def generate_synthetic_scenarios(self, count: int = 500) -> list[dict[str, Any]]:
        original_strategy = self.strategy
        initial_size = len(self.synthetic_records)
        self.strategy = "rule"
        attempts = 0
        while len(self.synthetic_records) - initial_size < count and attempts < count * 8:
            attempts += 1
            flow_id = self._pick_weighted_flow()
            team = self._pick_team_for_flow(flow_id) or self.random.choice(list(self.teams.values()))
            self._activate_team_request(team, flow_id)
            self._dispatch_requests()
            completed = False
            for vehicle in self.vehicles.values():
                if vehicle.team_assigned == team.id:
                    self._complete_vehicle_assignment(vehicle)
                    vehicle.status = VehicleStatus.IDLE
                    vehicle.available = True
                    vehicle.route_purpose = "idle"
                    vehicle.service_ticks_remaining = 0
                    completed = True
                    break
            if not completed:
                team.active_request = False
                team.assigned_vehicle_id = None
        self.strategy = original_strategy
        return self.synthetic_records[initial_size:]

    def _benchmark_engine(self, strategy: str, steps: int, scenario_seed: int) -> dict[str, Any]:
        engine = SimulationEngine(seed=scenario_seed)
        engine.configure_scenario(self.target_vehicle_count, self.target_team_count)
        engine.strategy = strategy
        engine.model_service = self.model_service
        engine.step(steps)
        metrics = engine.get_state()["metrics"]
        return {
            "completed_services": metrics["completed_services"],
            "avg_waiting_time_s": metrics["avg_waiting_time_s"],
            "avg_travel_time_s": metrics["avg_travel_time_s"],
            "avg_response_time_s": metrics["avg_response_time_s"],
            "route_recalculations": metrics["route_recalculations"],
            "occupancy_rate": metrics["occupancy_rate"],
            "teams_waiting": metrics["teams_waiting"],
        }

    def compare_strategies(self, steps: int = 30, scenarios: int = 5) -> dict[str, Any]:
        steps = max(1, min(steps, 300))
        scenarios = max(1, min(scenarios, 50))
        rule_runs = []
        ml_runs = []
        for index in range(scenarios):
            scenario_seed = self.seed + 100 + index
            rule_runs.append(self._benchmark_engine("rule", steps, scenario_seed))
            ml_runs.append(self._benchmark_engine("ml", steps, scenario_seed))

        def average(rows: list[dict[str, Any]]) -> dict[str, Any]:
            keys = rows[0].keys()
            summary: dict[str, Any] = {}
            for key in keys:
                values = [row[key] for row in rows]
                summary[key] = round(sum(values) / len(values), 2)
            return summary

        rule_avg = average(rule_runs)
        ml_avg = average(ml_runs)
        comparison = {
            "steps": steps,
            "scenarios": scenarios,
            "rule": rule_avg,
            "ml": ml_avg,
            "model_loaded": self.model_service.is_loaded,
            "ml_uses_regressor": self.model_service.has_regressor,
            "dominant_flow": self.dominant_flow,
        }
        comparison["delta"] = {
            "completed_services": round(ml_avg["completed_services"] - rule_avg["completed_services"], 2),
            "avg_waiting_time_s": round(ml_avg["avg_waiting_time_s"] - rule_avg["avg_waiting_time_s"], 2),
            "avg_travel_time_s": round(ml_avg["avg_travel_time_s"] - rule_avg["avg_travel_time_s"], 2),
            "avg_response_time_s": round(ml_avg["avg_response_time_s"] - rule_avg["avg_response_time_s"], 2),
        }
        comparison["winner"] = "ml" if ml_avg["avg_response_time_s"] < rule_avg["avg_response_time_s"] else "rule"
        self.last_comparison = comparison
        return comparison

    def _vehicle_remaining_eta(self, vehicle: Vehicle) -> float | None:
        if len(vehicle.route) < 2 or vehicle.route_index >= len(vehicle.route) - 1:
            return None
        remaining_time_s = 0.0
        if vehicle.route_index < len(vehicle.route) - 1:
            origin = vehicle.route[vehicle.route_index]
            target = vehicle.route[vehicle.route_index + 1]
            edge_key = vehicle.route_edge_keys[vehicle.route_index]
            edge = self.graph[origin][target][edge_key]
            remaining_distance = max(0.0, edge["distance_m"] - vehicle.progress_on_edge)
            edge_speed = max(self._target_vehicle_speed(vehicle, edge), 8.0) * (1000 / 3600)
            remaining_time_s += remaining_distance / edge_speed
        for offset in range(vehicle.route_index + 1, len(vehicle.route) - 1):
            u = vehicle.route[offset]
            v = vehicle.route[offset + 1]
            edge_key = vehicle.route_edge_keys[offset]
            edge = self.graph[u][v][edge_key]
            edge_speed = max(self._target_vehicle_speed(vehicle, edge), 8.0) * (1000 / 3600)
            remaining_time_s += edge["distance_m"] / edge_speed
        return round(remaining_time_s, 1)

    def _vehicle_route_progress_m(self, vehicle: Vehicle) -> float:
        if len(vehicle.route) < 2 or vehicle.route_index <= 0:
            return round(max(0.0, vehicle.progress_on_edge), 1)

        traveled = 0.0
        max_segment_index = min(vehicle.route_index, len(vehicle.route) - 1)
        for offset in range(max_segment_index):
            u = vehicle.route[offset]
            v = vehicle.route[offset + 1]
            edge_key = vehicle.route_edge_keys[offset]
            traveled += self.graph[u][v][edge_key]["distance_m"]
        traveled += max(0.0, vehicle.progress_on_edge)
        return round(traveled, 1)

    def _vehicle_route_id(self, vehicle: Vehicle) -> str:
        if len(vehicle.route) < 2 or len(vehicle.route_edge_keys) != len(vehicle.route) - 1:
            return ""
        signature = "|".join(
            f"{vehicle.route[index]}:{vehicle.route[index + 1]}:{vehicle.route_edge_keys[index]}"
            for index in range(len(vehicle.route) - 1)
        )
        return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]

    def _classify_turn(self, previous: tuple[float, float], current: tuple[float, float], nxt: tuple[float, float]) -> str:
        ax, ay = current[1] - previous[1], current[0] - previous[0]
        bx, by = nxt[1] - current[1], nxt[0] - current[0]
        cross = ax * by - ay * bx
        dot = ax * bx + ay * by
        norm_a = max((ax * ax + ay * ay) ** 0.5, 1e-6)
        norm_b = max((bx * bx + by * by) ** 0.5, 1e-6)
        angle = dot / (norm_a * norm_b)
        if angle > 0.96:
            return "Siga em frente"
        if cross > 0:
            return "Vire a esquerda"
        return "Vire a direita"

    def _build_navigation_instruction(self, vehicle: Vehicle) -> dict[str, Any]:
        if len(vehicle.route) < 2 or vehicle.route_index >= len(vehicle.route) - 1:
            return {
                "primary": "Aguardando proxima rota",
                "distance_to_action_m": 0,
                "direction": "straight",
            }

        origin = vehicle.route[vehicle.route_index]
        target = vehicle.route[vehicle.route_index + 1]
        edge_key = vehicle.route_edge_keys[vehicle.route_index]
        edge = self.graph[origin][target][edge_key]
        distance_to_action = max(0.0, edge["distance_m"] - vehicle.progress_on_edge)

        if vehicle.route_index + 2 < len(vehicle.route):
            current_pos = self.node_pos(origin)
            turn_pos = self.node_pos(target)
            next_pos = self.node_pos(vehicle.route[vehicle.route_index + 2])
            primary = self._classify_turn(current_pos, turn_pos, next_pos)
        else:
            primary = "Prossiga ate o destino"

        direction = "left" if "esquerda" in primary.lower() else "right" if "direita" in primary.lower() else "straight"
        return {
            "primary": primary,
            "distance_to_action_m": round(distance_to_action),
            "direction": direction,
        }

    def _build_vehicle_alerts(self, vehicle: Vehicle) -> list[str]:
        alerts: list[str] = []
        if vehicle.route_purpose == "service":
            alerts.append("Despacho ativo")
        if vehicle.status == VehicleStatus.RETURNING:
            alerts.append("Retornando a base")
        for event in self.events.values():
            if event.zone_id and event.zone_id == vehicle.current_zone_id:
                if event.event_type == "block":
                    alerts.append("Bloqueio a frente")
                elif event.event_type == "congestion":
                    alerts.append("Congestionamento detectado")
                else:
                    alerts.append("Reduza a velocidade")
        if not alerts:
            alerts.append("Operacao normal")
        return alerts[:3]

    def get_asset_details(self, asset_id: str) -> dict[str, Any] | None:
        self._sync_runtime()
        vehicle = self.vehicles.get(asset_id)
        if vehicle:
            eta_s = self._vehicle_remaining_eta(vehicle)
            route_id = self._vehicle_route_id(vehicle)
            return {
                "id": vehicle.id,
                "kind": "vehicle",
                "type": vehicle.vehicle_type,
                "status": vehicle.status.value,
                "speed_kmh": vehicle.current_speed_kmh,
                "max_speed_kmh": vehicle.speed_kmh,
                "current_zone_id": vehicle.current_zone_id,
                "base_zone_id": vehicle.base_zone_id,
                "flow_type": vehicle.flow_type,
                "route_purpose": vehicle.route_purpose,
                "eta_seconds": eta_s,
                "route_id": route_id,
                "route_progress_m": self._vehicle_route_progress_m(vehicle) if route_id else 0.0,
                "destination": vehicle.sequence_zones[vehicle.sequence_index] if vehicle.sequence_zones else vehicle.base_zone_id,
                "history": vehicle.history[-5:],
                "position": {"lat": vehicle.position[0], "lon": vehicle.position[1]},
            }
        team = self.teams.get(asset_id)
        if team:
            return {
                "id": team.id,
                "kind": "team",
                "role": team.role,
                "status": "waiting" if team.active_request else "idle",
                "zone_id": team.zone_id,
                "flow_type": team.flow_type,
                "priority": team.priority.value,
                "position": {"lat": team.position[0], "lon": team.position[1]},
            }
        return None

    def get_supervisor_dashboard(self) -> dict[str, Any]:
        self._sync_runtime()
        state = self.get_state()
        state["assets"] = [
            self.get_asset_details(vehicle.id)
            for vehicle in self.vehicles.values()
        ] + [
            self.get_asset_details(team.id)
            for team in self.teams.values()
        ]
        state["alerts"] = [
            {
                "id": event.id,
                "message": event.message or event.event_type,
                "zone_id": event.zone_id,
                "critical_point_id": event.critical_point_id,
                "severity": event.severity,
            }
            for event in self.events.values()
        ]
        return state

    def get_driver_dashboard(self, vehicle_id: str) -> dict[str, Any]:
        self._sync_runtime()
        vehicle = self.vehicles.get(vehicle_id)
        if not vehicle:
            raise KeyError(f"Vehicle {vehicle_id} not found")
        eta_s = self._vehicle_remaining_eta(vehicle)
        navigation = self._build_navigation_instruction(vehicle)
        route_id = self._vehicle_route_id(vehicle)
        return {
            "vehicle": {
                "id": vehicle.id,
                "type": vehicle.vehicle_type,
                "status": vehicle.status.value,
                "speed_kmh": vehicle.current_speed_kmh,
                "max_speed_kmh": vehicle.speed_kmh,
                "current_zone_id": vehicle.current_zone_id,
                "base_zone_id": vehicle.base_zone_id,
                "route_purpose": vehicle.route_purpose,
                "flow_type": vehicle.flow_type,
                "lat": vehicle.position[0],
                "lon": vehicle.position[1],
                "route_id": route_id,
                "route_progress_m": self._vehicle_route_progress_m(vehicle) if route_id else 0.0,
            },
            "navigation": navigation,
            "eta_seconds": eta_s,
            "destination": vehicle.sequence_zones[vehicle.sequence_index] if vehicle.sequence_zones else vehicle.base_zone_id,
            "alerts": self._build_vehicle_alerts(vehicle),
            "route_geometry": vehicle.route_geometry,
            "events": [
                asdict(event)
                for event in self.events.values()
                if event.zone_id == vehicle.current_zone_id or event.critical_point_id
            ][:5],
        }

    def get_state(self) -> dict[str, Any]:
        self._sync_runtime()
        blocked_edges = []
        graph_payload = {"nodes": [], "edges": []}
        for node_id, attrs in self.graph.nodes(data=True):
            graph_payload["nodes"].append(
                {
                    "id": str(node_id),
                    "raw_id": node_id,
                    "lat": attrs["y"],
                    "lon": attrs["x"],
                    "kind": attrs.get("kind", "road_node"),
                    "sector": attrs.get("sector", "network"),
                    "label": attrs.get("label", f"Node {node_id}"),
                }
            )
        for u, v, edge_key, attrs in self.graph.edges(keys=True, data=True):
            edge_row = {
                "id": f"{u}:{v}:{edge_key}",
                "from": u,
                "to": v,
                "key": edge_key,
                "coordinates": attrs["geometry_coords"],
                "distance_m": attrs["distance_m"],
                "base_time_s": attrs["base_time_s"],
                "capacity": attrs["capacity"],
                "road_type": attrs["road_type"],
                "blocked": attrs["blocked"],
                "congestion": attrs["congestion"],
                "speed_kmh": attrs["speed_kmh"],
                "from_osm": attrs.get("from_osm", False),
                "oneway": attrs.get("oneway", False),
                "operational_zone": attrs.get("operational_zone"),
                "criticality": attrs.get("criticality", 0.0),
                "critical_point_ids": attrs.get("critical_point_ids", []),
                "dominant_flows": attrs.get("dominant_flows", []),
            }
            graph_payload["edges"].append(edge_row)
            if attrs["blocked"]:
                blocked_edges.append(edge_row)

        active_team_count = sum(1 for team in self.teams.values() if team.active_request)
        avg_waiting = sum(team.waiting_time_seconds for team in self.teams.values() if team.active_request) / max(active_team_count, 1)
        avg_travel = self.total_travel_time_s / max(self.total_completed_services, 1)
        avg_response = self.total_response_time_s / max(self.total_completed_services, 1)
        occupancy = sum(1 for vehicle in self.vehicles.values() if not vehicle.available) / max(len(self.vehicles), 1)
        moving_vehicles = [vehicle.current_speed_kmh for vehicle in self.vehicles.values() if vehicle.current_speed_kmh > 0]

        debug_payload = {
            "operation_sites": [
                {
                    "id": site_id,
                    "label": site["label"],
                    "kind": site["kind"],
                    "original_position": [site["lat"], site["lon"]],
                    "snapped_position": list(site["snapped_position"]),
                    "node_position": list(site["node_position"]),
                    "node_id": str(site["node_id"]),
                    "distance_to_edge_m": site["distance_to_edge_m"],
                }
                for site_id, site in self.operation_sites.items()
            ],
            "discarded_edges": self.graph.graph.get("debug_discarded_edges", [])[:250],
            "discarded_edge_count": self.graph.graph.get("discarded_edge_count", 0),
        }

        return {
            "meta": {
                "tick": self.tick,
                "tick_seconds": self.tick_seconds,
                "ticks_enabled": self.ticks_enabled,
                "tick_mode_seconds": self.tick_mode_seconds,
                "timestamp": self.simulation_timestamp(),
                "running": self.running,
                "speed_multiplier": self.speed_multiplier,
                "strategy": self.strategy,
                "model_loaded": self.model_service.is_loaded,
                "port_center": {"lat": PORT_CENTER[0], "lon": PORT_CENTER[1]},
                "debug_mode": self.debug_mode,
                "dominant_flow": self.dominant_flow,
                "scenario": {
                    "vehicle_count": self.target_vehicle_count,
                    "team_count": self.target_team_count,
                },
            },
            "graph": graph_payload,
            "zones": [
                {
                    "id": zone["id"],
                    "label": zone["label"],
                    "kind": zone["kind"],
                    "color": zone["color"],
                    "icon": zone["icon"],
                    "center": list(zone["center"]),
                    "radius_m": zone["radius_m"],
                    "anchor_positions": [list(anchor) for anchor in zone["anchor_positions"]],
                    "vehicle_density": self.zone_vehicle_density.get(zone["id"], 0),
                    "waiting_teams": self.zone_active_requests.get(zone["id"], 0),
                }
                for zone in self.zones.values()
            ],
            "critical_points": [
                {
                    "id": point["id"],
                    "label": point["label"],
                    "zone_id": point["zone_id"],
                    "icon": point["icon"],
                    "weight": point["weight"],
                    "position": list(point["position"]),
                }
                for point in self.critical_points.values()
            ],
            "flows": [
                {
                    "id": flow_id,
                    "label": flow["label"],
                    "sequence": flow["sequence"],
                    "priority": flow["priority"],
                    "is_dominant": flow_id == self.dominant_flow,
                }
                for flow_id, flow in FLOW_DEFINITIONS.items()
            ],
            "vehicles": [
                {
                    "id": vehicle.id,
                    "type": vehicle.vehicle_type,
                    "lat": vehicle.position[0],
                    "lon": vehicle.position[1],
                    "speed_kmh": vehicle.current_speed_kmh,
                    "max_speed_kmh": vehicle.speed_kmh,
                    "status": vehicle.status.value,
                    "available": vehicle.available,
                    "route": [str(node_id) for node_id in vehicle.route],
                    "route_geometry": vehicle.route_geometry,
                    "capacity": vehicle.capacity,
                    "team_assigned": vehicle.team_assigned,
                    "sector": vehicle.sector,
                    "history": vehicle.history[-5:],
                    "current_node": str(vehicle.current_node),
                    "base_zone_id": vehicle.base_zone_id,
                    "current_zone_id": vehicle.current_zone_id,
                    "route_purpose": vehicle.route_purpose,
                    "flow_type": vehicle.flow_type,
                    "rail_only": vehicle.rail_only,
                    "route_id": self._vehicle_route_id(vehicle),
                    "route_progress_m": self._vehicle_route_progress_m(vehicle) if self._vehicle_route_id(vehicle) else 0.0,
                }
                for vehicle in self.vehicles.values()
            ],
            "teams": [
                {
                    "id": team.id,
                    "node_id": str(team.node_id),
                    "lat": team.position[0],
                    "lon": team.position[1],
                    "priority": team.priority.value,
                    "active_request": team.active_request,
                    "waiting_time_seconds": team.waiting_time_seconds,
                    "service_type": team.service_type,
                    "sector": team.sector,
                    "assigned_vehicle_id": team.assigned_vehicle_id,
                    "zone_id": team.zone_id,
                    "role": team.role,
                    "demand_origin_zone": team.demand_origin_zone,
                    "demand_destination_zone": team.demand_destination_zone,
                    "flow_type": team.flow_type,
                }
                for team in self.teams.values()
            ],
            "events": [asdict(event) for event in self.events.values()],
            "metrics": {
                "active_vehicles": sum(1 for vehicle in self.vehicles.values() if not vehicle.available),
                "vehicles_total": len(self.vehicles),
                "teams_waiting": active_team_count,
                "avg_speed_kmh": round(sum(moving_vehicles) / max(len(moving_vehicles), 1), 2),
                "avg_waiting_time_s": round(avg_waiting, 2),
                "avg_travel_time_s": round(avg_travel, 2),
                "avg_response_time_s": round(avg_response, 2),
                "blocked_segments": len(blocked_edges),
                "occupancy_rate": round(occupancy, 3),
                "route_recalculations": self.total_route_recalculations,
                "synthetic_records": len(self.synthetic_records),
                "completed_services": self.total_completed_services,
                "discarded_edges": debug_payload["discarded_edge_count"],
                "dominant_flow": self.dominant_flow,
                "critical_hotspots": len(self.critical_points),
            },
            "debug": debug_payload,
            "comparison": self.last_comparison,
        }
