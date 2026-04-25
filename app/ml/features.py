from __future__ import annotations

from app.simulation.entities import FieldTeam, Vehicle


def build_candidate_feature_row(
    *,
    timestamp: str,
    team: FieldTeam,
    vehicle: Vehicle,
    route_metrics: dict,
    observed_time_s: float,
    is_best_vehicle: bool,
    origin_zone_density: int,
    destination_zone_density: int,
) -> dict:
    return {
        "timestamp": timestamp,
        "team_id": team.id,
        "vehicle_id": vehicle.id,
        "distance_to_team_m": route_metrics["distance_m"],
        "base_eta_s": route_metrics["estimated_time_s"],
        "priority_weighted_eta_s": route_metrics.get("priority_weighted_eta_s", route_metrics["estimated_time_s"]),
        "route_edge_count": route_metrics["edge_count"],
        "blocked_edges_in_path": route_metrics["blocked_edges"],
        "avg_congestion": route_metrics["avg_congestion"],
        "origin_zone": route_metrics.get("origin_zone", vehicle.current_zone_id),
        "destination_zone": route_metrics.get("destination_zone", team.zone_id),
        "flow_type": route_metrics.get("flow_type", team.flow_type),
        "criticality_score": route_metrics.get("criticality_score", 0.0),
        "origin_zone_density": origin_zone_density,
        "destination_zone_density": destination_zone_density,
        "vehicle_type": vehicle.vehicle_type,
        "team_priority": team.priority.value,
        "vehicle_status": vehicle.status.value,
        "operation_sector": team.sector,
        "team_role": team.role,
        "vehicle_base_zone": vehicle.base_zone_id,
        "observed_travel_time_s": observed_time_s,
        "observed_response_time_s": observed_time_s + team.waiting_time_seconds,
        "best_vehicle_label": int(is_best_vehicle),
        "vehicle_capacity": vehicle.capacity,
        "vehicle_speed_kmh": vehicle.speed_kmh,
        "team_waiting_time_s": team.waiting_time_seconds,
    }
