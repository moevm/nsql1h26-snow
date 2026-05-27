import logging
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import get_current_user
from app.api.rate_limit import limiter
from app.models.schemas import RouteCreate, RouteRead, RouteUpdate, LatLng, WaypointItem

router = APIRouter()
logger = logging.getLogger(__name__)

async def _build_route_through_waypoints(graph, ordered_coords: list[dict]):
    all_nodes_latlng = []
    all_node_ids = []
    streets = set()
    total_distance = 0.0

    for i in range(len(ordered_coords) - 1):
        a = ordered_coords[i]
        b = ordered_coords[i + 1]

        a_node = await graph.find_nearest_node(a["lat"], a["lng"])
        b_node = await graph.find_nearest_node(b["lat"], b["lng"])
        if not a_node or not b_node:
            return None

        path = await graph.find_shortest_path(a_node["id"], b_node["id"])
        if not path:
            return None

        roads = await graph.find_path_roads(a_node["id"], b_node["id"])

        nodes = path["nodes"]
        if all_nodes_latlng:
            nodes = nodes[1:]

        all_nodes_latlng.extend([{"lat": n["lat"], "lng": n["lng"]} for n in nodes])
        all_node_ids.extend([n["id"] for n in nodes])

        for r in roads:
            if r.get("name"):
                streets.add(r["name"])
        total_distance += sum(r.get("distance", 0) for r in roads)

    return all_nodes_latlng, all_node_ids, streets, total_distance

@router.post("/", response_model=RouteRead, status_code=201)
@limiter.limit("30/minute")
async def create_route(request: Request, body: RouteCreate, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao

    all_wp_coords = [{"lat": body.start.lat, "lng": body.start.lng}]
    for wp in body.waypoints:
        all_wp_coords.append({"lat": wp.lat, "lng": wp.lng})
    all_wp_coords.append({"lat": body.end.lat, "lng": body.end.lng})

    if body.path_nodes:
        path_nodes_data = [{"lat": n.lat, "lng": n.lng} for n in body.path_nodes]
        start_node = await graph.find_nearest_node(body.start.lat, body.start.lng)
        end_node = await graph.find_nearest_node(body.end.lat, body.end.lng)
        if not start_node or not end_node:
            raise HTTPException(status_code=404, detail="Cannot find nodes near given coordinates")
        roads = await graph.find_path_roads(start_node["id"], end_node["id"])
        streets = sorted({r["name"] for r in roads if r.get("name")})
        distance_m = round(sum(r.get("distance", 0) for r in roads), 1)
        node_ids = []
    else:
        result = await _build_route_through_waypoints(graph, all_wp_coords)
        if not result:
            raise HTTPException(status_code=404, detail="No route found between given waypoints")
        path_nodes_data, node_ids, streets_set, distance_m = result
        streets = sorted(streets_set)
        distance_m = round(distance_m, 1)

    route_id = str(uuid.uuid4())[:8]
    route_data = {
        "id": route_id,
        "label": body.label or "",
        "start_lat": body.start.lat,
        "start_lng": body.start.lng,
        "end_lat": body.end.lat,
        "end_lng": body.end.lng,
        "path_nodes_json": json.dumps(path_nodes_data, default=str),
        "streets": streets,
        "distance_m": distance_m,
    }
    await graph.create_route(route_data)
    await graph.link_created_route(user, route_id)

    if node_ids:
        await graph.create_route_point_links(route_id, node_ids)

    wp_entries = []
    for i, coord in enumerate(all_wp_coords):
        n = await graph.find_nearest_node(coord["lat"], coord["lng"])
        if n:
            role = "start" if i == 0 else ("end" if i == len(all_wp_coords) - 1 else "waypoint")
            wp_entries.append({"point_id": n["id"], "role": role, "index": i})
    if wp_entries:
        await graph.create_waypoint_links(route_id, wp_entries)

    created = await graph.get_route(route_id)
    if not created:
        raise HTTPException(status_code=500, detail="Route was not persisted")
    return _row_to_route(created)

@router.get("/", response_model=dict)
@limiter.limit("60/minute")
async def list_routes(
    request: Request,
    label: str | None = None,
    distance_min: float | None = None,
    distance_max: float | None = None,
    streets_min: int | None = None,
    streets_max: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    updated_at_from: str | None = None,
    updated_at_to: str | None = None,
    started_at_from: str | None = None,
    started_at_to: str | None = None,
    finished_at_from: str | None = None,
    finished_at_to: str | None = None,
    path_nodes_min: int | None = None,
    path_nodes_max: int | None = None,
    route_id_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user: str = Depends(get_current_user),
):
    graph = request.app.state.graph_dao
    result = await graph.get_routes_paged(
        page=page, page_size=page_size,
        label=label, distance_min=distance_min, distance_max=distance_max,
        streets_min=streets_min, streets_max=streets_max,
        date_from=date_from, date_to=date_to,
        updated_at_from=updated_at_from, updated_at_to=updated_at_to,
        started_at_from=started_at_from, started_at_to=started_at_to,
        finished_at_from=finished_at_from, finished_at_to=finished_at_to,
        path_nodes_min=path_nodes_min, path_nodes_max=path_nodes_max,
        route_id_filter=route_id_filter,
    )
    raw_items = result["items"]
    converted = [_row_to_route(row) for row in raw_items]
    result["items"] = [
        {**item.model_dump(), "path_nodes_count": raw.get("path_nodes_count", 0)}
        for item, raw in zip(converted, raw_items)
    ]
    return result

@router.get("/{route_id}", response_model=RouteRead)
@limiter.limit("60/minute")
async def get_route(request: Request, route_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    row = await graph.get_route(route_id)
    if not row:
        raise HTTPException(status_code=404, detail="Route not found")
    return _row_to_route(row)

@router.patch("/{route_id}", response_model=RouteRead)
@limiter.limit("30/minute")
async def update_route(request: Request, route_id: str, body: RouteUpdate, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    existing = await graph.get_route(route_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Route not found")

    updates = body.model_dump(exclude_none=True)
    if updates:
        await graph.update_route(route_id, updates)

    row = await graph.get_route(route_id)
    if not row:
        raise HTTPException(status_code=404, detail="Route not found")
    return _row_to_route(row)

@router.delete("/{route_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_route(request: Request, route_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    existing = await graph.get_route(route_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Route not found")
    await graph.delete_route(route_id)

@router.get("/{route_id}/points")
async def get_route_points(
    request: Request, route_id: str,
    page: int = 1, page_size: int = 20,
    user: str = Depends(get_current_user),
):
    graph = request.app.state.graph_dao
    return await graph.get_route_points_paged(route_id, page=page, page_size=page_size)

@router.get("/{route_id}/waypoints")
async def get_route_waypoints(
    request: Request, route_id: str,
    page: int = 1, page_size: int = 20,
    user: str = Depends(get_current_user),
):
    graph = request.app.state.graph_dao
    return await graph.get_route_waypoints_paged(route_id, page=page, page_size=page_size)

@router.post("/{route_id}/waypoint", status_code=201)
@limiter.limit("30/minute")
async def add_waypoint(request: Request, route_id: str, body: WaypointItem, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    existing = await graph.get_route(route_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Route not found")

    nearest = await graph.find_nearest_node(body.lat, body.lng)
    if not nearest:
        raise HTTPException(status_code=404, detail="No node near given coordinates")

    current_wps = sorted(await graph.get_route_waypoints(route_id), key=lambda w: w.get("index", 0))

    new_wps: list[dict] = []

    if body.role == "start":
        others = [w for w in current_wps if w.get("role") != "start"]
        new_wps = [{"point_id": nearest["id"], "role": "start", "index": 0}]
        for idx, w in enumerate(others, start=1):
            new_wps.append({"point_id": w["id"], "role": w["role"], "index": idx})

    elif body.role == "end":
        others = [w for w in current_wps if w.get("role") != "end"]
        new_wps = [{"point_id": w["id"], "role": w["role"], "index": i} for i, w in enumerate(others)]
        new_wps.append({"point_id": nearest["id"], "role": "end", "index": len(new_wps)})

    else:
        non_end = [w for w in current_wps if w.get("role") != "end"]
        end_wps = [w for w in current_wps if w.get("role") == "end"]
        new_wps = [{"point_id": w["id"], "role": w["role"], "index": i} for i, w in enumerate(non_end)]
        new_idx = len(new_wps)
        new_wps.append({"point_id": nearest["id"], "role": "waypoint", "index": new_idx})
        for w in end_wps:
            new_wps.append({"point_id": w["id"], "role": "end", "index": new_idx + 1})

    await graph.delete_route_waypoints(route_id)
    if new_wps:
        await graph.create_waypoint_links(route_id, new_wps)

    updated_wps = sorted(await graph.get_route_waypoints(route_id), key=lambda w: w.get("index", 0))
    ordered_coords = [{"lat": w["lat"], "lng": w["lng"]} for w in updated_wps if w.get("lat") and w.get("lng")]

    if len(ordered_coords) >= 2:
        result = await _build_route_through_waypoints(graph, ordered_coords)
        if result:
            path_nodes_data, node_ids, streets_set, distance_m = result
            route_updates = {
                "start_lat": ordered_coords[0]["lat"],
                "start_lng": ordered_coords[0]["lng"],
                "end_lat": ordered_coords[-1]["lat"],
                "end_lng": ordered_coords[-1]["lng"],
                "path_nodes_json": json.dumps(path_nodes_data),
                "streets": sorted(streets_set),
                "distance_m": round(distance_m, 1),
            }
            await graph.update_route(route_id, route_updates)
            await graph.delete_route_contains_points(route_id)
            if node_ids:
                await graph.create_route_point_links(route_id, node_ids)

    return {"status": "added", "role": body.role}

def _row_to_route(row: dict) -> RouteRead:
    return RouteRead(
        id=row["id"],
        label=row["label"] or "",
        start=LatLng(lat=row["start_lat"], lng=row["start_lng"]),
        end=LatLng(lat=row["end_lat"], lng=row["end_lng"]),
        path_nodes=_parse_path_nodes(row.get("path_nodes_json")),
        streets=list(row.get("streets") or []),
        distance_m=float(row.get("distance_m") or 0),
        created_at=_coerce_datetime(row.get("created_at")) or datetime.utcnow(),
        updated_at=_coerce_datetime(row.get("updated_at")),
        started_at=_coerce_datetime(row.get("started_at")),
        finished_at=_coerce_datetime(row.get("finished_at")),
    )

def _coerce_datetime(value):
    if value is None or value == "datetime()":
        return None
    native = getattr(value, "to_native", None)
    if callable(native):
        return native()
    return value

def _parse_path_nodes(raw_value: str | None) -> list[LatLng]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        logger.warning("Failed to parse path_nodes_json for route")
        return []
    nodes: list[LatLng] = []
    for item in parsed:
        if isinstance(item, dict) and "lat" in item and "lng" in item:
            nodes.append(LatLng(lat=item["lat"], lng=item["lng"]))
    return nodes
