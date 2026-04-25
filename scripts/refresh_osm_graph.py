from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.routing.graph_loader import GRAPHML_CACHE, METADATA_CACHE, build_operation_sites, build_port_graph


def main() -> None:
    graph = build_port_graph(force_refresh=True)
    sites = build_operation_sites(graph)
    print(f"Graph cached at: {GRAPHML_CACHE}")
    print(f"Metadata cached at: {METADATA_CACHE}")
    print(f"Nodes: {graph.number_of_nodes()} | Edges: {graph.number_of_edges()} | Sites: {len(sites)}")


if __name__ == "__main__":
    main()
