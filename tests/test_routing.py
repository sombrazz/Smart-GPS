import networkx as nx

from app.routing.graph_loader import build_operation_sites, build_port_graph, snap_point_to_graph
from app.routing.router import Router


def test_real_graph_has_valid_route_between_operation_sites():
    graph = build_port_graph()
    sites = build_operation_sites(graph)
    router = Router(graph)
    route = router.shortest_path(sites["gate_north"]["node_id"], sites["pier_3"]["node_id"])
    assert route is not None
    assert route.distance_m > 0
    assert len(route.geometry) >= 2


def test_blocked_edge_changes_path_on_unit_graph():
    graph = nx.MultiDiGraph()
    graph.add_node("a", x=0.0, y=0.0, pos=(0.0, 0.0))
    graph.add_node("b", x=0.001, y=0.0, pos=(0.0, 0.001))
    graph.add_node("c", x=0.002, y=0.0, pos=(0.0, 0.002))
    graph.add_node("d", x=0.001, y=0.001, pos=(0.001, 0.001))
    base_attrs = {"capacity": 0.4, "road_type": "service", "congestion": 0.1, "speed_kmh": 18, "lanes": 1, "from_osm": True}
    graph.add_edge("a", "b", distance_m=10, base_time_s=2, blocked=False, geometry_coords=[(0.0, 0.0), (0.0, 0.001)], **base_attrs)
    graph.add_edge("b", "c", distance_m=10, base_time_s=2, blocked=False, geometry_coords=[(0.0, 0.001), (0.0, 0.002)], **base_attrs)
    graph.add_edge("a", "d", distance_m=12, base_time_s=3, blocked=False, geometry_coords=[(0.0, 0.0), (0.001, 0.001)], **base_attrs)
    graph.add_edge("d", "c", distance_m=12, base_time_s=3, blocked=False, geometry_coords=[(0.001, 0.001), (0.0, 0.002)], **base_attrs)

    router = Router(graph)
    baseline = router.shortest_path("a", "c")
    assert baseline is not None
    graph["b"]["c"][0]["blocked"] = True
    rerouted = router.shortest_path("a", "c")
    assert rerouted is not None
    assert rerouted.path != baseline.path


def test_snap_point_to_graph_returns_valid_node():
    graph = nx.MultiDiGraph()
    graph.add_node("a", x=-44.37, y=-2.565, pos=(-2.565, -44.37))
    graph.add_node("b", x=-44.369, y=-2.565, pos=(-2.565, -44.369))
    graph.add_edge(
        "a",
        "b",
        distance_m=100,
        base_time_s=10,
        capacity=0.4,
        road_type="service",
        blocked=False,
        congestion=0.1,
        speed_kmh=20,
        lanes=1,
        from_osm=True,
        geometry_coords=[(-2.565, -44.37), (-2.565, -44.369)],
    )
    snapped = snap_point_to_graph(graph, -2.56502, -44.3697, label="unit")
    assert snapped["node_id"] in {"a", "b"}
    assert snapped["distance_to_edge_m"] < 20
