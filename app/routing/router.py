from __future__ import annotations

from dataclasses import asdict
from typing import Any, Hashable

import networkx as nx

from app.simulation.entities import RoutePlan


class Router:
    def __init__(self, graph: nx.MultiDiGraph):
        self.graph = graph

    def edge_cost(
        self,
        edge_data: dict[str, Any],
        vehicle_speed_kmh: float | None = None,
        *,
        allowed_road_types: set[str] | None = None,
        origin_zone: str | None = None,
        target_zone: str | None = None,
        flow_type: str | None = None,
        dominant_flow: str | None = None,
    ) -> float:
        if edge_data.get("blocked", False):
            return float("inf")
        if allowed_road_types and edge_data.get("road_type") not in allowed_road_types:
            return float("inf")
        congestion_factor = 1.0 + edge_data.get("congestion", 0.0) * 1.8
        critical_factor = 1.0 + edge_data.get("criticality", 0.0) * 1.35
        road_factor = {
            "rail": 0.82,
            "motorway": 0.9,
            "trunk": 0.95,
            "primary": 1.0,
            "secondary": 1.05,
            "tertiary": 1.08,
            "unclassified": 1.12,
            "residential": 1.15,
            "service": 1.18,
            "road": 1.2,
            "living_street": 1.25,
        }.get(edge_data.get("road_type"), 1.15)
        effective_speed = edge_data["speed_kmh"]
        if vehicle_speed_kmh is not None:
            effective_speed = min(edge_data["speed_kmh"], vehicle_speed_kmh)
        base_time_s = edge_data["distance_m"] / max(effective_speed * (1000 / 3600), 0.1)
        zone_bias = 1.0
        operational_zone = edge_data.get("operational_zone")
        if target_zone and operational_zone == target_zone:
            zone_bias *= 0.95
        if origin_zone and operational_zone == origin_zone:
            zone_bias *= 0.97
        if dominant_flow and dominant_flow in edge_data.get("dominant_flows", []):
            zone_bias *= 0.93
        if flow_type and flow_type in edge_data.get("dominant_flows", []):
            zone_bias *= 0.90
        return base_time_s * congestion_factor * critical_factor * road_factor * zone_bias

    def _best_edge_key(
        self,
        u: Hashable,
        v: Hashable,
        vehicle_speed_kmh: float | None = None,
        *,
        allowed_road_types: set[str] | None = None,
        origin_zone: str | None = None,
        target_zone: str | None = None,
        flow_type: str | None = None,
        dominant_flow: str | None = None,
    ) -> tuple[int | str, dict[str, Any]]:
        edge_bundle = self.graph.get_edge_data(u, v)
        if not edge_bundle:
            raise nx.NetworkXNoPath(f"No edge between {u} and {v}")
        best_key = min(
            edge_bundle,
            key=lambda key: self.edge_cost(
                edge_bundle[key],
                vehicle_speed_kmh,
                allowed_road_types=allowed_road_types,
                origin_zone=origin_zone,
                target_zone=target_zone,
                flow_type=flow_type,
                dominant_flow=dominant_flow,
            ),
        )
        return best_key, edge_bundle[best_key]

    def shortest_path(
        self,
        source: Hashable,
        target: Hashable,
        *,
        vehicle_speed_kmh: float | None = None,
        allowed_road_types: set[str] | None = None,
        origin_zone: str | None = None,
        target_zone: str | None = None,
        flow_type: str | None = None,
        dominant_flow: str | None = None,
    ) -> RoutePlan | None:
        def weight(u: Hashable, v: Hashable, edge_bundle: dict) -> float:
            if not edge_bundle:
                return float("inf")
            return min(
                self.edge_cost(
                    attrs,
                    vehicle_speed_kmh,
                    allowed_road_types=allowed_road_types,
                    origin_zone=origin_zone,
                    target_zone=target_zone,
                    flow_type=flow_type,
                    dominant_flow=dominant_flow,
                )
                for attrs in edge_bundle.values()
            )

        try:
            path = nx.dijkstra_path(self.graph, source, target, weight=weight)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

        edges = list(zip(path, path[1:]))
        if not edges:
            return RoutePlan("", "", [source], [], [self.graph.nodes[source]["pos"]], 0.0, 0.0, 0, 0.0, 0)

        distance_m = 0.0
        estimated_time_s = 0.0
        blocked_edges = 0
        avg_congestion = 0.0
        route_geometry: list[tuple[float, float]] = []
        edge_keys: list[int | str] = []

        for u, v in edges:
            edge_key, data = self._best_edge_key(
                u,
                v,
                vehicle_speed_kmh,
                allowed_road_types=allowed_road_types,
                origin_zone=origin_zone,
                target_zone=target_zone,
                flow_type=flow_type,
                dominant_flow=dominant_flow,
            )
            edge_keys.append(edge_key)
            distance_m += data["distance_m"]
            estimated_time_s += self.edge_cost(
                data,
                vehicle_speed_kmh,
                allowed_road_types=allowed_road_types,
                origin_zone=origin_zone,
                target_zone=target_zone,
                flow_type=flow_type,
                dominant_flow=dominant_flow,
            )
            blocked_edges += int(bool(data.get("blocked")))
            avg_congestion += data.get("congestion", 0.0)
            coords = data.get("geometry_coords", [self.graph.nodes[u]["pos"], self.graph.nodes[v]["pos"]])
            if route_geometry and coords and route_geometry[-1] == coords[0]:
                route_geometry.extend(coords[1:])
            else:
                route_geometry.extend(coords)
        avg_congestion = avg_congestion / len(edges)

        return RoutePlan(
            vehicle_id="",
            team_id="",
            path=path,
            edge_keys=edge_keys,
            geometry=route_geometry,
            distance_m=distance_m,
            estimated_time_s=estimated_time_s,
            blocked_edges=blocked_edges,
            avg_congestion=avg_congestion,
            edge_count=len(edges),
        )

    def evaluate_vehicle_options(
        self,
        vehicle_ids: list[str],
        vehicle_node_lookup: dict[str, Hashable],
        team_id: str,
        team_node: Hashable,
        priorities: dict[str, str],
        available_lookup: dict[str, bool],
        vehicle_speed_lookup: dict[str, float],
        vehicle_edge_type_lookup: dict[str, set[str]],
        vehicle_zone_lookup: dict[str, str],
        team_zone: str,
        flow_type: str,
        dominant_flow: str,
    ) -> list[dict]:
        evaluations: list[dict] = []
        for vehicle_id in vehicle_ids:
            if not available_lookup.get(vehicle_id, False):
                continue
            plan = self.shortest_path(
                vehicle_node_lookup[vehicle_id],
                team_node,
                vehicle_speed_kmh=vehicle_speed_lookup.get(vehicle_id),
                allowed_road_types=vehicle_edge_type_lookup.get(vehicle_id),
                origin_zone=vehicle_zone_lookup.get(vehicle_id),
                target_zone=team_zone,
                flow_type=flow_type,
                dominant_flow=dominant_flow,
            )
            if plan is None:
                continue
            priority_weight = {
                "low": 1.0,
                "medium": 0.95,
                "high": 0.9,
                "critical": 0.82,
            }.get(priorities.get(team_id, "medium"), 1.0)
            total_score = plan.estimated_time_s * priority_weight + (plan.avg_congestion * 120.0)
            row = asdict(plan)
            row["vehicle_id"] = vehicle_id
            row["team_id"] = team_id
            row["origin_zone"] = vehicle_zone_lookup.get(vehicle_id)
            row["destination_zone"] = team_zone
            row["flow_type"] = flow_type
            row["score"] = total_score
            evaluations.append(row)
        evaluations.sort(key=lambda item: item["score"])
        return evaluations
