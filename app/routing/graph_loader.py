from __future__ import annotations

import json
import math
import warnings
from typing import Any, Hashable

import networkx as nx

try:
    import osmnx as ox
except ModuleNotFoundError:
    ox = None

from app.core.settings import DATA_DIR


PORT_CENTER = (-2.565, -44.370)
OSM_RADIUS_METERS = 2_400
MAX_SNAP_DISTANCE_METERS = 300.0
OSM_CACHE_DIR = DATA_DIR / "osm"
OSM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
GRAPHML_CACHE = OSM_CACHE_DIR / "ponta_da_madeira_drive_service.graphml"
METADATA_CACHE = OSM_CACHE_DIR / "ponta_da_madeira_metadata.json"

ALLOWED_HIGHWAYS = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "service",
    "road",
    "living_street",
}

DEFAULT_SPEEDS = {
    "motorway": 70,
    "trunk": 60,
    "primary": 45,
    "secondary": 38,
    "tertiary": 32,
    "unclassified": 25,
    "residential": 22,
    "service": 18,
    "road": 18,
    "living_street": 15,
}

DEFAULT_CAPACITY = {
    "motorway": 0.95,
    "trunk": 0.9,
    "primary": 0.8,
    "secondary": 0.7,
    "tertiary": 0.6,
    "unclassified": 0.5,
    "residential": 0.45,
    "service": 0.4,
    "road": 0.35,
    "living_street": 0.3,
}

OPERATION_SITE_SEEDS = [
    {"id": "gate_main", "label": "Gate Principal", "kind": "gate", "sector": "gate", "lat": -2.5568, "lon": -44.3815},
    {"id": "gate_buffer", "label": "Pulmao Gate", "kind": "gate", "sector": "gate", "lat": -2.5602, "lon": -44.3788},
    {"id": "crossroads_main", "label": "Cruzamento Principal", "kind": "intersection", "sector": "crossroads", "lat": -2.5630, "lon": -44.3706},
    {"id": "crossroads_south", "label": "Cruzamento Sul", "kind": "intersection", "sector": "crossroads", "lat": -2.5683, "lon": -44.3780},
    {"id": "rail_arrival", "label": "Area Ferroviaria", "kind": "rail", "sector": "rail", "lat": -2.5597, "lon": -44.3691},
    {"id": "rail_crossing", "label": "Travessia Ferroviaria", "kind": "rail", "sector": "rail", "lat": -2.5624, "lon": -44.3755},
    {"id": "yard_west", "label": "Patio Oeste", "kind": "yard", "sector": "yard", "lat": -2.5651, "lon": -44.3812},
    {"id": "yard_central", "label": "Patio Central", "kind": "yard", "sector": "yard", "lat": -2.5658, "lon": -44.3741},
    {"id": "yard_east", "label": "Patio Leste", "kind": "yard", "sector": "yard", "lat": -2.5652, "lon": -44.3667},
    {"id": "warehouse", "label": "Armazens", "kind": "warehouse", "sector": "warehouse", "lat": -2.5583, "lon": -44.3646},
    {"id": "pier_access", "label": "Acesso ao Pier", "kind": "pier_access", "sector": "pier", "lat": -2.5696, "lon": -44.3672},
    {"id": "pier_1", "label": "Berco 1", "kind": "pier", "sector": "pier", "lat": -2.5612, "lon": -44.3621},
    {"id": "pier_2", "label": "Berco 2", "kind": "pier", "sector": "pier", "lat": -2.5661, "lon": -44.3602},
    {"id": "pier_3", "label": "Berco 3", "kind": "pier", "sector": "pier", "lat": -2.5712, "lon": -44.3605},
    {"id": "maintenance_base", "label": "Manutencao e Estacionamento", "kind": "maintenance", "sector": "maintenance", "lat": -2.5706, "lon": -44.3729},
    {"id": "support_parking", "label": "Base de Apoio", "kind": "service", "sector": "maintenance", "lat": -2.5674, "lon": -44.3738},
]

ZONE_DEFINITIONS = {
    "gate": {
        "label": "Gate principal",
        "kind": "gate",
        "site_ids": ["gate_main", "gate_buffer"],
        "radius_m": 320.0,
        "color": "#f4d7a1",
        "icon": "gate",
    },
    "crossroads": {
        "label": "Cruzamentos viarios",
        "kind": "crossroads",
        "site_ids": ["crossroads_main", "crossroads_south"],
        "radius_m": 260.0,
        "color": "#f6c7b8",
        "icon": "crossroads",
    },
    "rail": {
        "label": "Area ferroviaria",
        "kind": "rail",
        "site_ids": ["rail_arrival", "rail_crossing"],
        "radius_m": 280.0,
        "color": "#cce0f6",
        "icon": "rail",
    },
    "yard": {
        "label": "Patio de minerio",
        "kind": "yard",
        "site_ids": ["yard_west", "yard_central", "yard_east"],
        "radius_m": 360.0,
        "color": "#d8e8c8",
        "icon": "yard",
    },
    "warehouse": {
        "label": "Armazens",
        "kind": "warehouse",
        "site_ids": ["warehouse"],
        "radius_m": 220.0,
        "color": "#eadfc8",
        "icon": "warehouse",
    },
    "pier": {
        "label": "Acesso ao pier e bercos",
        "kind": "pier",
        "site_ids": ["pier_access", "pier_1", "pier_2", "pier_3"],
        "radius_m": 360.0,
        "color": "#c8e8e5",
        "icon": "pier",
    },
    "maintenance": {
        "label": "Manutencao e estacionamento",
        "kind": "maintenance",
        "site_ids": ["maintenance_base", "support_parking"],
        "radius_m": 260.0,
        "color": "#e4d2f3",
        "icon": "maintenance",
    },
}

CRITICAL_POINT_DEFINITIONS = [
    {"id": "gate_main", "label": "Gate principal", "zone_id": "gate", "site_id": "gate_main", "weight": 1.0, "icon": "gate"},
    {"id": "crossroads_main", "label": "Cruzamento principal", "zone_id": "crossroads", "site_id": "crossroads_main", "weight": 0.92, "icon": "crossroads"},
    {"id": "rail_arrival", "label": "Area ferroviaria", "zone_id": "rail", "site_id": "rail_arrival", "weight": 0.88, "icon": "rail"},
    {"id": "pier_access", "label": "Acesso ao pier", "zone_id": "pier", "site_id": "pier_access", "weight": 0.95, "icon": "pier"},
    {"id": "maintenance_base", "label": "Manutencao e estacionamento", "zone_id": "maintenance", "site_id": "maintenance_base", "weight": 0.76, "icon": "maintenance"},
]

FLOW_DEFINITIONS = {
    "rail_yard_pier": {
        "label": "Ferrovia -> patio -> pier",
        "sequence": ["rail", "yard", "pier", "yard"],
        "vehicle_types": {"train", "truck", "pickup"},
        "priority": "high",
        "request_zones": ["yard", "pier"],
    },
    "gate_warehouse_pier": {
        "label": "Gate -> armazens -> pier",
        "sequence": ["gate", "warehouse", "pier", "gate"],
        "vehicle_types": {"support", "pickup"},
        "priority": "medium",
        "request_zones": ["gate", "warehouse", "pier"],
    },
    "maintenance_patrol": {
        "label": "Manutencao no patio",
        "sequence": ["maintenance", "yard", "crossroads", "maintenance"],
        "vehicle_types": {"utility", "support"},
        "priority": "medium",
        "request_zones": ["yard", "maintenance", "crossroads"],
    },
}


def approximate_distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat_scale = 111_320
    lon_scale = 111_320 * math.cos(math.radians((a[0] + b[0]) / 2))
    dy = (b[0] - a[0]) * lat_scale
    dx = (b[1] - a[1]) * lon_scale
    return math.sqrt(dx * dx + dy * dy)


def local_xy(lat: float, lon: float, reference: tuple[float, float] = PORT_CENTER) -> tuple[float, float]:
    lat_scale = 111_320
    lon_scale = 111_320 * math.cos(math.radians(reference[0]))
    return ((lon - reference[1]) * lon_scale, (lat - reference[0]) * lat_scale)


def _project_point_on_segment(
    point_xy: tuple[float, float],
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
) -> tuple[float, tuple[float, float]]:
    segment_x = end_xy[0] - start_xy[0]
    segment_y = end_xy[1] - start_xy[1]
    if segment_x == 0 and segment_y == 0:
        return math.dist(point_xy, start_xy), start_xy
    projection = (
        ((point_xy[0] - start_xy[0]) * segment_x + (point_xy[1] - start_xy[1]) * segment_y)
        / (segment_x * segment_x + segment_y * segment_y)
    )
    projection = max(0.0, min(1.0, projection))
    projected = (
        start_xy[0] + projection * segment_x,
        start_xy[1] + projection * segment_y,
    )
    return math.dist(point_xy, projected), projected


def interpolate_along_coordinates(coords: list[tuple[float, float]], distance_m: float) -> tuple[float, float]:
    if len(coords) == 1:
        return coords[0]
    total_length = 0.0
    segments: list[tuple[float, tuple[float, float], tuple[float, float]]] = []
    for start, end in zip(coords, coords[1:]):
        length = approximate_distance_m(start, end)
        segments.append((length, start, end))
        total_length += length
    if total_length <= 0:
        return coords[-1]
    remaining = max(0.0, min(distance_m, total_length))
    for length, start, end in segments:
        if remaining <= length:
            fraction = 0.0 if length == 0 else remaining / length
            return (
                start[0] + (end[0] - start[0]) * fraction,
                start[1] + (end[1] - start[1]) * fraction,
            )
        remaining -= length
    return coords[-1]


def _highway_values(edge_data: dict[str, Any]) -> set[str]:
    value = edge_data.get("highway")
    if value is None:
        return set()
    if isinstance(value, list):
        return {str(item) for item in value}
    return {str(value)}


def _pick_highway_type(edge_data: dict[str, Any]) -> str:
    values = _highway_values(edge_data)
    for candidate in values:
        if candidate in ALLOWED_HIGHWAYS:
            return candidate
    return next(iter(values), "service")


def _is_driveable(edge_data: dict[str, Any]) -> bool:
    if edge_data.get("area") == "yes":
        return False
    access = str(edge_data.get("access", "")).lower()
    if access in {"no", "customers"}:
        return False
    if str(edge_data.get("motor_vehicle", "")).lower() == "no":
        return False
    values = _highway_values(edge_data)
    return bool(values & ALLOWED_HIGHWAYS)


def _parse_speed(edge_data: dict[str, Any], highway_type: str) -> float:
    value = edge_data.get("maxspeed")
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            return float(digits)
    return float(DEFAULT_SPEEDS.get(highway_type, 18))


def _road_type_to_capacity(highway_type: str) -> float:
    return float(DEFAULT_CAPACITY.get(highway_type, 0.35))


def _base_congestion(highway_type: str) -> float:
    return {
        "motorway": 0.08,
        "trunk": 0.10,
        "primary": 0.12,
        "secondary": 0.14,
        "tertiary": 0.18,
        "unclassified": 0.20,
        "residential": 0.22,
        "service": 0.25,
        "road": 0.24,
        "living_street": 0.28,
    }.get(highway_type, 0.22)


def add_synthetic_rail_corridors(
    graph: nx.MultiDiGraph,
    operation_sites: dict[str, dict[str, Any]],
) -> nx.MultiDiGraph:
    rail_layout = {
        "rail_arrival": (-2.5599, -44.3702),
        "rail_crossing": (-2.5617, -44.3734),
        "yard_central": (-2.5642, -44.3745),
        "yard_east": (-2.5649, -44.3682),
        "pier_access": (-2.5684, -44.3651),
        "pier_2": (-2.5662, -44.3609),
    }
    rail_links = [
        ("rail_arrival", "rail_crossing"),
        ("rail_crossing", "yard_central"),
        ("yard_central", "yard_east"),
        ("yard_east", "pier_access"),
        ("pier_access", "pier_2"),
    ]
    rail_nodes: dict[str, str] = {}

    for site_id, position in rail_layout.items():
        site = operation_sites.get(site_id)
        node_id = f"rail::{site_id}"
        rail_nodes[site_id] = node_id
        graph.add_node(
            node_id,
            x=float(position[1]),
            y=float(position[0]),
            pos=(float(position[0]), float(position[1])),
            kind="rail_node",
            sector="rail",
            label=f"Rail {site['label'] if site else site_id}",
        )

    for start_id, end_id in rail_links:
        u = rail_nodes[start_id]
        v = rail_nodes[end_id]
        coords = [graph_node_position(graph, u), graph_node_position(graph, v)]
        distance_m = sum(approximate_distance_m(a, b) for a, b in zip(coords, coords[1:]))

        for origin, target, geometry in ((u, v, coords), (v, u, list(reversed(coords)))):
            edge_key = f"rail::{start_id}->{end_id}" if origin == u else f"rail::{end_id}->{start_id}"
            graph.add_edge(
                origin,
                target,
                key=edge_key,
                distance_m=distance_m,
                base_time_s=distance_m / max(28 * (1000 / 3600), 0.1),
                capacity=1.4,
                road_type="rail",
                blocked=False,
                congestion=0.08,
                speed_kmh=28.0,
                lanes=1,
                geometry_coords=geometry,
                from_osm=False,
                discarded=False,
                osmid=None,
                name=f"Corredor ferroviario {start_id}-{end_id}",
                bridge=None,
                oneway=False,
                operational_zone="rail",
                criticality=0.0,
                dominant_flows=["rail_yard_pier"],
                critical_point_ids=[],
            )
    graph.graph["rail_site_nodes"] = rail_nodes
    return graph


def _download_raw_osm_graph() -> nx.MultiDiGraph:
    if ox is None:
        raise ModuleNotFoundError("osmnx is required to download the OSM graph")
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(OSM_CACHE_DIR)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="The expected order of coordinates in `bbox` will change.*")
        return ox.graph_from_point(
            PORT_CENTER,
            dist=OSM_RADIUS_METERS,
            dist_type="bbox",
            network_type="drive_service",
            simplify=True,
            retain_all=False,
        )


def _load_or_download_raw_osm_graph(force_refresh: bool = False) -> nx.MultiDiGraph:
    if GRAPHML_CACHE.exists() and not force_refresh:
        if ox is not None:
            return ox.load_graphml(GRAPHML_CACHE)
        return nx.read_graphml(GRAPHML_CACHE)

    raw_graph = _download_raw_osm_graph()
    if ox is not None:
        ox.save_graphml(raw_graph, GRAPHML_CACHE)
    return raw_graph


def _normalize_osm_graph(raw_graph: nx.MultiDiGraph) -> tuple[nx.MultiDiGraph, dict[str, Any]]:
    graph = nx.MultiDiGraph(name="porto_ponta_da_madeira_osm")
    discarded_edges: list[dict[str, Any]] = []

    for node_id, data in raw_graph.nodes(data=True):
        graph.add_node(
            node_id,
            x=float(data["x"]),
            y=float(data["y"]),
            pos=(float(data["y"]), float(data["x"])),
            kind="road_node",
            sector="network",
            label=f"Node {node_id}",
        )

    for u, v, edge_key, edge_data in raw_graph.edges(keys=True, data=True):
        geometry = edge_data.get("geometry")
        coordinates: list[tuple[float, float]] | None = None
        if geometry is not None and hasattr(geometry, "coords"):
            coordinates = [(float(lat), float(lon)) for lon, lat in geometry.coords]
        elif str(raw_graph.nodes[u].get("y", "")).strip() and str(raw_graph.nodes[v].get("y", "")).strip():
            coordinates = [
                (float(raw_graph.nodes[u]["y"]), float(raw_graph.nodes[u]["x"])),
                (float(raw_graph.nodes[v]["y"]), float(raw_graph.nodes[v]["x"])),
            ]

        if not _is_driveable(edge_data):
            discarded_edges.append({"from": u, "to": v, "reason": "highway_not_allowed", "coordinates": coordinates})
            continue

        highway_type = _pick_highway_type(edge_data)
        if not coordinates or len(coordinates) < 2:
            discarded_edges.append({"from": u, "to": v, "reason": "degenerate_geometry", "coordinates": coordinates})
            continue

        edge_length = float(edge_data.get("length") or sum(approximate_distance_m(a, b) for a, b in zip(coordinates, coordinates[1:])))
        if edge_length <= 1.0:
            discarded_edges.append({"from": u, "to": v, "reason": "zero_length", "coordinates": coordinates})
            continue

        speed_kmh = _parse_speed(edge_data, highway_type)
        base_time_s = edge_length / max(speed_kmh * (1000 / 3600), 0.1)
        attrs = {
            "distance_m": edge_length,
            "base_time_s": base_time_s,
            "capacity": _road_type_to_capacity(highway_type),
            "road_type": highway_type,
            "blocked": False,
            "congestion": _base_congestion(highway_type),
            "speed_kmh": speed_kmh,
            "lanes": edge_data.get("lanes", 1),
            "geometry_coords": coordinates,
            "from_osm": True,
            "discarded": False,
            "osmid": edge_data.get("osmid"),
            "name": edge_data.get("name"),
            "bridge": edge_data.get("bridge"),
            "oneway": edge_data.get("oneway", False),
            "operational_zone": None,
            "criticality": 0.0,
            "critical_point_ids": [],
            "dominant_flows": [],
        }
        graph.add_edge(u, v, key=edge_key, **attrs)

    largest_component = max(nx.weakly_connected_components(graph), key=len)
    graph = graph.subgraph(largest_component).copy()

    metadata = {
        "discarded_edges": discarded_edges,
        "discarded_edge_count": len(discarded_edges),
        "source": "OpenStreetMap via OSMnx",
        "center": {"lat": PORT_CENTER[0], "lon": PORT_CENTER[1]},
        "radius_m": OSM_RADIUS_METERS,
    }
    graph.graph["debug_discarded_edges"] = discarded_edges
    graph.graph["discarded_edge_count"] = len(discarded_edges)
    return graph, metadata


def build_port_graph(force_refresh: bool = False) -> nx.MultiDiGraph:
    raw_graph = _load_or_download_raw_osm_graph(force_refresh=force_refresh)
    graph, metadata = _normalize_osm_graph(raw_graph)
    if force_refresh or not METADATA_CACHE.exists():
        METADATA_CACHE.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return graph


def graph_node_position(graph: nx.MultiDiGraph, node_id: Hashable) -> tuple[float, float]:
    data = graph.nodes[node_id]
    return (float(data["y"]), float(data["x"]))


def snap_point_to_graph(
    graph: nx.MultiDiGraph,
    lat: float,
    lon: float,
    *,
    label: str,
    max_distance_m: float = MAX_SNAP_DISTANCE_METERS,
) -> dict[str, Any]:
    point_xy = local_xy(lat, lon)
    nearest_edge: tuple[Hashable, Hashable] | None = None
    nearest_edge_distance = math.inf
    snapped_latlon = (lat, lon)
    nearest_node_id: Hashable | None = None
    nearest_node_distance = math.inf
    for u, v, edge_key, data in graph.edges(keys=True, data=True):
        coords = data.get("geometry_coords", [])
        if len(coords) < 2:
            continue
        xy_coords = [local_xy(edge_lat, edge_lon) for edge_lat, edge_lon in coords]
        best_segment_distance = math.inf
        best_projected_xy = xy_coords[0]
        for start_xy, end_xy in zip(xy_coords, xy_coords[1:]):
            candidate_distance, projected_xy = _project_point_on_segment(point_xy, start_xy, end_xy)
            if candidate_distance < best_segment_distance:
                best_segment_distance = candidate_distance
                best_projected_xy = projected_xy
        if best_segment_distance < nearest_edge_distance:
            nearest_edge_distance = best_segment_distance
            nearest_edge = (u, v)
            snapped_latlon = (
                PORT_CENTER[0] + best_projected_xy[1] / 111_320,
                PORT_CENTER[1] + best_projected_xy[0] / (111_320 * math.cos(math.radians(PORT_CENTER[0]))),
            )
            u_distance = approximate_distance_m((lat, lon), graph_node_position(graph, u))
            v_distance = approximate_distance_m((lat, lon), graph_node_position(graph, v))
            if u_distance <= v_distance:
                nearest_node_id = u
                nearest_node_distance = u_distance
            else:
                nearest_node_id = v
                nearest_node_distance = v_distance

    if nearest_edge is None or nearest_node_id is None or nearest_edge_distance > max_distance_m:
        raise ValueError(f"Could not snap point '{label}' to a valid drivable edge within {max_distance_m}m")

    return {
        "node_id": nearest_node_id,
        "node_position": graph_node_position(graph, nearest_node_id),
        "snapped_position": snapped_latlon,
        "nearest_edge": nearest_edge,
        "distance_to_edge_m": round(float(nearest_edge_distance), 2),
        "distance_to_node_m": round(float(nearest_node_distance), 2),
    }


def build_operation_sites(graph: nx.MultiDiGraph) -> dict[str, dict[str, Any]]:
    strongly_connected_nodes = max(nx.strongly_connected_components(graph), key=len)
    nodes = [
        {
            "node_id": node_id,
            "lat": float(data["y"]),
            "lon": float(data["x"]),
        }
        for node_id, data in graph.nodes(data=True)
        if node_id in strongly_connected_nodes
    ]
    lat_min = min(node["lat"] for node in nodes)
    lat_max = max(node["lat"] for node in nodes)
    lon_min = min(node["lon"] for node in nodes)
    lon_max = max(node["lon"] for node in nodes)
    used_nodes: set[Hashable] = set()

    def normalized(node: dict[str, Any]) -> tuple[float, float]:
        lat_norm = 0.5 if lat_max == lat_min else (node["lat"] - lat_min) / (lat_max - lat_min)
        lon_norm = 0.5 if lon_max == lon_min else (node["lon"] - lon_min) / (lon_max - lon_min)
        return lat_norm, lon_norm

    targets = {
        "gate_main": (0.95, 0.10),
        "gate_buffer": (0.83, 0.18),
        "crossroads_main": (0.55, 0.46),
        "crossroads_south": (0.28, 0.24),
        "rail_arrival": (0.70, 0.58),
        "rail_crossing": (0.63, 0.31),
        "yard_west": (0.48, 0.18),
        "yard_central": (0.48, 0.42),
        "yard_east": (0.48, 0.72),
        "warehouse": (0.72, 0.80),
        "pier_access": (0.34, 0.74),
        "pier_1": (0.72, 0.90),
        "pier_2": (0.48, 0.93),
        "pier_3": (0.24, 0.93),
        "maintenance_base": (0.24, 0.38),
        "support_parking": (0.31, 0.34),
    }

    def derived_site(seed: dict[str, Any]) -> dict[str, Any]:
        target = targets[seed["id"]]
        best_node = None
        best_score = math.inf
        for node in nodes:
            lat_norm, lon_norm = normalized(node)
            score = math.dist((lat_norm, lon_norm), target)
            if node["node_id"] in used_nodes:
                score += 0.08
            if score < best_score:
                best_score = score
                best_node = node
        assert best_node is not None
        used_nodes.add(best_node["node_id"])
        return {
            **seed,
            "node_id": best_node["node_id"],
            "node_position": (best_node["lat"], best_node["lon"]),
            "snapped_position": (best_node["lat"], best_node["lon"]),
            "nearest_edge": None,
            "distance_to_edge_m": 0.0,
            "distance_to_node_m": 0.0,
            "selection_method": "derived_from_network",
        }

    sites: dict[str, dict[str, Any]] = {}
    for seed in OPERATION_SITE_SEEDS:
        try:
            snapped = snap_point_to_graph(graph, seed["lat"], seed["lon"], label=seed["id"])
            if snapped["distance_to_edge_m"] <= 400.0 and snapped["node_id"] in strongly_connected_nodes:
                used_nodes.add(snapped["node_id"])
                sites[seed["id"]] = {
                    **seed,
                    **snapped,
                    "selection_method": "snapped_seed",
                }
                continue
        except ValueError:
            pass
        sites[seed["id"]] = derived_site(seed)
    aliases = {
        "gate_north": "gate_main",
        "gate_south": "gate_buffer",
        "maintenance": "maintenance_base",
        "admin": "rail_crossing",
        "checkpoint_alpha": "crossroads_main",
        "checkpoint_beta": "crossroads_south",
        "fuel": "support_parking",
        "ops_tower": "warehouse",
    }
    for alias, source_id in aliases.items():
        if source_id in sites:
            sites[alias] = {**sites[source_id], "id": alias, "selection_method": f"alias_of_{source_id}"}
    return sites


def build_operational_zones(graph: nx.MultiDiGraph, operation_sites: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    zones: dict[str, dict[str, Any]] = {}
    for zone_id, config in ZONE_DEFINITIONS.items():
        anchors = [operation_sites[site_id] for site_id in config["site_ids"] if site_id in operation_sites]
        anchor_positions = [site["node_position"] for site in anchors]
        centroid = (
            sum(lat for lat, _ in anchor_positions) / max(len(anchor_positions), 1),
            sum(lon for _, lon in anchor_positions) / max(len(anchor_positions), 1),
        )

        node_distances: list[tuple[float, Hashable]] = []
        for node_id in graph.nodes:
            node_pos = graph_node_position(graph, node_id)
            nearest_anchor_distance = min(approximate_distance_m(node_pos, anchor) for anchor in anchor_positions)
            node_distances.append((nearest_anchor_distance, node_id))
        node_distances.sort(key=lambda item: item[0])

        zone_nodes = [node_id for distance, node_id in node_distances if distance <= config["radius_m"]]
        if len(zone_nodes) < 24:
            zone_nodes = [node_id for _, node_id in node_distances[:24]]

        zones[zone_id] = {
            "id": zone_id,
            "label": config["label"],
            "kind": config["kind"],
            "color": config["color"],
            "icon": config["icon"],
            "radius_m": config["radius_m"],
            "site_ids": list(config["site_ids"]),
            "anchor_positions": anchor_positions,
            "center": centroid,
            "node_ids": zone_nodes,
        }
    return zones


def build_critical_points(operation_sites: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    critical_points: dict[str, dict[str, Any]] = {}
    for definition in CRITICAL_POINT_DEFINITIONS:
        site = operation_sites[definition["site_id"]]
        critical_points[definition["id"]] = {
            "id": definition["id"],
            "label": definition["label"],
            "zone_id": definition["zone_id"],
            "icon": definition["icon"],
            "weight": definition["weight"],
            "site_id": definition["site_id"],
            "node_id": site["node_id"],
            "position": site["node_position"],
        }
    return critical_points


def _edge_midpoint(coords: list[tuple[float, float]]) -> tuple[float, float]:
    return interpolate_along_coordinates(coords, sum(approximate_distance_m(a, b) for a, b in zip(coords, coords[1:])) / 2)


def annotate_graph_with_operational_context(
    graph: nx.MultiDiGraph,
    zones: dict[str, dict[str, Any]],
    critical_points: dict[str, dict[str, Any]],
) -> nx.MultiDiGraph:
    for _, _, _, data in graph.edges(keys=True, data=True):
        coords = data.get("geometry_coords", [])
        if len(coords) < 2:
            continue
        midpoint = _edge_midpoint(coords)
        zone_distances = {
            zone_id: min(approximate_distance_m(midpoint, anchor) for anchor in zone["anchor_positions"])
            for zone_id, zone in zones.items()
        }
        zone_id, zone_distance = min(zone_distances.items(), key=lambda item: item[1])
        if zone_distance <= zones[zone_id]["radius_m"]:
            data["operational_zone"] = zone_id

        critical_refs: list[str] = []
        criticality = 0.0
        for point_id, point in critical_points.items():
            distance = approximate_distance_m(midpoint, point["position"])
            if distance <= 220.0:
                critical_refs.append(point_id)
                criticality = max(criticality, max(0.1, point["weight"] * (1 - distance / 260.0)))

        data["critical_point_ids"] = critical_refs
        data["criticality"] = round(min(1.0, criticality), 3)

        if critical_refs:
            data["congestion"] = min(0.88, data["congestion"] + 0.10 + data["criticality"] * 0.22)
            data["capacity"] = max(0.12, data["capacity"] * (1.0 - data["criticality"] * 0.45))
            data["speed_kmh"] = max(8.0, data["speed_kmh"] * (1.0 - data["criticality"] * 0.18))

        dominant_flows: list[str] = []
        for flow_id, flow in FLOW_DEFINITIONS.items():
            if data["operational_zone"] in flow["sequence"]:
                dominant_flows.append(flow_id)
        data["dominant_flows"] = dominant_flows
    return graph
