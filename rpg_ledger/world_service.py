from __future__ import annotations

from typing import Any, Optional, List, Dict

import networkx as nx

from . import storage


def find_route(
    campaign_id: str,
    from_id: Optional[str] = None,
    to_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Znajdź trasę między lokacjami kampanii."""
    data = storage.load_campaign(campaign_id)
    locations = data.get("locations") or []
    if not locations:
        raise ValueError("campaign has no locations defined")

    id_to_loc: Dict[str, Dict[str, Any]] = {}
    for loc in locations:
        lid = str(loc.get("id") or "")
        if not lid:
            continue
        id_to_loc[lid] = loc

    if not id_to_loc:
        raise ValueError("no valid locations with 'id' in campaign")

    current_id = str(data.get("current_location_id") or "").strip()
    if not current_id:
        current_name = str(data.get("location") or "").strip()
        for lid, loc in id_to_loc.items():
            if str(loc.get("name") or "").strip() == current_name:
                current_id = lid
                break
        if not current_id:
            current_id = next(iter(id_to_loc.keys()))

    start_id = from_id or current_id
    if not start_id:
        raise ValueError("from_id could not be determined")
    if to_id is None:
        raise ValueError("to_id is required")
    start_id = str(start_id)
    to_id = str(to_id)

    if start_id not in id_to_loc:
        raise ValueError(f"unknown from_id: {start_id!r}")
    if to_id not in id_to_loc:
        raise ValueError(f"unknown to_id: {to_id!r}")

    g = nx.Graph()
    for lid in id_to_loc.keys():
        g.add_node(lid)

    connections = data.get("connections") or []
    if connections:
        for conn in connections:
            a = str(conn.get("from") or "")
            b = str(conn.get("to") or "")
            if not a or not b:
                continue
            if a not in id_to_loc or b not in id_to_loc:
                continue
            distance = conn.get("distance")
            try:
                weight = float(distance) if distance is not None else 1.0
            except Exception:
                weight = 1.0
            g.add_edge(a, b, weight=weight, meta=conn)
    else:
        g.add_edge(start_id, to_id, weight=1.0, meta=None)

    try:
        path_ids = nx.shortest_path(g, start_id, to_id, weight="weight")
        total_weight = nx.path_weight(g, path_ids, weight="weight")
    except Exception as e:
        raise ValueError(f"cannot find route from {start_id!r} to {to_id!r}: {e}")

    path_locs = [
        {
            "id": lid,
            "name": id_to_loc[lid].get("name") or lid,
            "type": id_to_loc[lid].get("type"),
            "tags": id_to_loc[lid].get("tags"),
        }
        for lid in path_ids
    ]

    edges: List[Dict[str, Any]] = []
    for a, b in zip(path_ids, path_ids[1:]):
        data_edge = g.get_edge_data(a, b) or {}
        meta = data_edge.get("meta") or {}
        edges.append(
            {
                "from": a,
                "to": b,
                "distance": data_edge.get("weight"),
                "meta": meta,
            }
        )

    return {
        "campaign_id": campaign_id,
        "from_id": start_id,
        "to_id": to_id,
        "path": path_locs,
        "total_distance": total_weight,
        "edges": edges,
    }

