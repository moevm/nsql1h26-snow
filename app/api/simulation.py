import json
import json as _json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import get_current_user
from app.api.rate_limit import limiter
from app.models.enums import SimulationStatus, VehicleStatus, VehicleType
from app.models.schemas import LatLng, SimulationCreate, SimulationParams, SimulationState, VehicleState
from app.services.simulation_engine import SimulationEngine

router = APIRouter()
logger = logging.getLogger(__name__)

_simulations: dict[str, SimulationEngine] = {}

def _get_engine(sim_id: str) -> SimulationEngine:
    if sim_id not in _simulations:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return _simulations[sim_id]

async def _restore_engine(request: Request, sim_id: str) -> SimulationEngine:
    graph = request.app.state.graph_dao
    cache = request.app.state.cache
    row = await graph.get_simulation(sim_id)
    if not row:
        raise HTTPException(status_code=404, detail="Simulation not found")

    params_raw = json.loads(row.get("params_json", "{}")) if row.get("params_json") else {}
    params = SimulationParams.model_validate(params_raw or {})
    engine = SimulationEngine(sim_id, params, graph, cache)
    engine._vehicle_cfg_by_type = {cfg.type: cfg for cfg in params.vehicles}
    engine.state = SimulationState.model_validate(_node_to_state_dict(row))

    route_rows = await graph.get_simulation_routes(sim_id)
    all_road_segments: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()

    for route_row in route_rows:
        raw_nodes = route_row.get("path_nodes_json") or "[]"
        try:
            path_nodes = json.loads(raw_nodes)
        except Exception:
            path_nodes = []
        if path_nodes:
            engine.route_coords.append(path_nodes)

        for street in route_row.get("streets") or []:
            if street:
                engine._streets.add(street)

        route_points = await graph.get_route_points(route_row["id"])
        ordered = sorted(route_points, key=lambda p: p.get("index", 0))
        route_seg_total = 0
        for i in range(len(ordered) - 1):
            src = ordered[i]
            dst = ordered[i + 1]
            edge_key = (src["id"], dst["id"])
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            all_road_segments.append({
                "src": src["id"],
                "dst": dst["id"],
                "src_lat": src["lat"],
                "src_lng": src["lng"],
                "dst_lat": dst["lat"],
                "dst_lng": dst["lng"],
                "name": None,
                "distance": 0,
                "route_id": route_row["id"],
            })
            engine._register_edge_route(src["id"], dst["id"], route_row["id"])
            route_seg_total += 1
        if route_seg_total:
            engine._route_stats[route_row["id"]] = {
                "total": route_seg_total,
                "cleaned": 0,
                "started": bool(route_row.get("started_at")),
            }

    roads_total = int(row.get("roads_total") or len(all_road_segments))
    roads_total = min(roads_total, len(all_road_segments)) if all_road_segments else roads_total
    cleaned_guess = int(round((float(row.get("roads_cleaned_pct") or 0.0) / 100.0) * roads_total)) if roads_total else 0
    cleaned_guess = max(0, min(cleaned_guess, len(all_road_segments)))

    for idx, road in enumerate(all_road_segments):
        if idx >= cleaned_guess:
            break
        route_id = road.get("route_id")
        if route_id and route_id in engine._route_stats:
            engine._route_stats[route_id]["cleaned"] += 1
            engine._route_stats[route_id]["started"] = True
        engine._cleaned_edges.add(f"{road['src']}->{road['dst']}")

    engine._uncleaned = all_road_segments[cleaned_guess:]
    engine._roads_total = roads_total or len(all_road_segments)
    engine._roads_cleaned = cleaned_guess
    engine._all_roads_done = not engine._uncleaned and engine._roads_cleaned >= engine._roads_total
    engine._streets = set(row.get("streets") or list(engine._streets))
    engine.state.streets = sorted(engine._streets)
    if all_road_segments:
        await engine._load_facilities(all_road_segments[0])

    latest_vehicle_rows = await graph.get_latest_simulation_vehicle_states(sim_id)
    engine.vehicles = []
    for vehicle in latest_vehicle_rows:
        vehicle_type = VehicleType(vehicle.get("vehicle_type") or "tractor")
        cfg = engine._vehicle_cfg_by_type.get(vehicle_type)
        travel_speed = vehicle.get("travel_speed_kmh")
        cleaning_speed = vehicle.get("cleaning_speed_kmh")
        legacy_speed = vehicle.get("speed_kmh")
        engine.vehicles.append(
            VehicleState(
                id=vehicle["id"],
                type=vehicle_type,
                status=VehicleStatus(vehicle.get("status") or "idle"),
                location=LatLng(lat=float(vehicle.get("lat") or 0.0), lng=float(vehicle.get("lng") or 0.0)),
                home_parking_id=vehicle.get("home_parking_id"),
                home_parking_location=LatLng(
                    lat=float(vehicle.get("home_parking_lat") or 0.0),
                    lng=float(vehicle.get("home_parking_lng") or 0.0),
                ) if vehicle.get("home_parking_lat") is not None and vehicle.get("home_parking_lng") is not None else None,
                fuel_level=float(vehicle.get("fuel_level") or 0.0),
                snow_loaded_m3=float(vehicle.get("snow_loaded_m3") or 0.0),
                distance_travelled_km=float(vehicle.get("distance_travelled_km") or 0.0),
                speed_kmh=float(legacy_speed or 0.0),
                travel_speed_kmh=float(travel_speed or (cfg.travel_speed_kmh if cfg else legacy_speed or 30.0)),
                cleaning_speed_kmh=float(cleaning_speed or (cfg.cleaning_speed_kmh if cfg else legacy_speed or 10.0)),
                fuel_consumption_l_per_km=float(vehicle.get("fuel_consumption_l_per_km") or (cfg.fuel_consumption_l_per_km if cfg else 0.4)),
                fuel_capacity_l=float(vehicle.get("fuel_capacity_l") or 0.0),
                snow_capacity_m3=float(vehicle.get("snow_capacity_m3") or 0.0),
                breakdown_probability=float(vehicle.get("breakdown_probability") or 0.0),
                repair_time_min=float(vehicle.get("repair_time_min") or (cfg.repair_time_min if cfg else 60.0)),
                repair_remaining_min=float(vehicle.get("repair_remaining_min") or 0.0),
                target_type=vehicle.get("target_type"),
                target_id=vehicle.get("target_id"),
                target_location=LatLng(
                    lat=float(vehicle.get("target_lat") or 0.0),
                    lng=float(vehicle.get("target_lng") or 0.0),
                ) if vehicle.get("target_lat") is not None and vehicle.get("target_lng") is not None else None,
                road_target_location=LatLng(
                    lat=float(vehicle.get("road_target_lat") or 0.0),
                    lng=float(vehicle.get("road_target_lng") or 0.0),
                ) if vehicle.get("road_target_lat") is not None and vehicle.get("road_target_lng") is not None else None,
                road_resume_location=LatLng(
                    lat=float(vehicle.get("road_resume_lat") or 0.0),
                    lng=float(vehicle.get("road_resume_lng") or 0.0),
                ) if vehicle.get("road_resume_lat") is not None and vehicle.get("road_resume_lng") is not None else None,
                progress_m=float(vehicle.get("progress_m") or 0.0),
                current_edge=vehicle.get("current_edge"),
                current_road=vehicle.get("current_road"),
            )
        )
    engine._refresh_state_metrics()

    _simulations[sim_id] = engine
    logger.info("Simulation %s restored from DB into memory", sim_id)
    return engine

async def _get_or_restore_engine(request: Request, sim_id: str) -> SimulationEngine:
    if sim_id in _simulations:
        return _simulations[sim_id]
    return await _restore_engine(request, sim_id)

async def _persist_simulation(graph, engine: SimulationEngine, name: str | None = None) -> None:
    state = engine.state
    sim_data = {
        "id": state.id,
        "status": state.status.value if hasattr(state.status, 'value') else str(state.status),
        "tick": state.tick,
        "elapsed_minutes": state.elapsed_minutes,
        "vehicles_total": sum(cfg.count for cfg in engine.params.vehicles),
        "vehicles_active": state.vehicles_active,
        "vehicles_broken": state.vehicles_broken,
        "vehicles_en_route": state.vehicles_en_route,
        "vehicles_cleaning": state.vehicles_cleaning,
        "vehicles_dumping": state.vehicles_dumping,
        "vehicles_refueling": state.vehicles_refueling,
        "vehicles_maintenance": state.vehicles_maintenance,
        "roads_cleaned_pct": state.roads_cleaned_pct,
        "snow_collected_m3": state.snow_collected_m3,
        "fuel_spent_l": state.fuel_spent_l,
        "avg_fuel_pct": state.avg_fuel_pct,
        "avg_snow_load_pct": state.avg_snow_load_pct,
        "streets": state.streets,
        "roads_total": engine._roads_total,
        "route_coords_json": json.dumps(engine.route_coords, default=str),
        "started_at": state.started_at,
        "finished_at": state.finished_at,
        "params_json": json.dumps(engine.params.model_dump(), default=str),
    }
    existing = await graph.get_simulation(state.id)
    if existing:
        sim_data.pop("id")
        await graph.update_simulation(state.id, sim_data)
    else:
        sim_data["name"] = name
        await graph.create_simulation(sim_data)

@router.post("/start", status_code=201)
@limiter.limit("5/minute")
async def start_simulation(
    request: Request,
    body: SimulationCreate,
    user: str = Depends(get_current_user),
):
    if not body.params.cleaning_tasks:
        raise HTTPException(status_code=400, detail="Добавьте хотя бы один маршрут уборки")

    sim_id = str(uuid.uuid4())[:8]
    graph = request.app.state.graph_dao
    cache = request.app.state.cache

    engine = SimulationEngine(sim_id, body.params, graph, cache)
    try:
        await engine.initialize()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    engine.state.name = body.name
    _simulations[sim_id] = engine

    await _persist_simulation(graph, engine, name=body.name)
    await graph.link_created_simulation(user, sim_id)

    for i, coords in enumerate(engine.route_coords):
        if not coords:
            continue
        task = body.params.cleaning_tasks[i] if i < len(body.params.cleaning_tasks) else None

        if task and task.route_id:
            existing = await graph.get_route(task.route_id)
            if existing:
                await graph.create_simulation_route_link(sim_id, task.route_id)
                continue

        route_id = f"{sim_id}-r{i}"
        node_ids = [n["id"] for n in coords if "id" in n]
        route_data = {
            "id": route_id,
            "label": (task.label if task and task.label else f"Маршрут {i+1}"),
            "start_lat": coords[0]["lat"],
            "start_lng": coords[0]["lng"],
            "end_lat": coords[-1]["lat"],
            "end_lng": coords[-1]["lng"],
            "streets": list(engine._streets)[:20],
            "distance_m": 0.0,
            "path_nodes_json": _json.dumps(coords),
        }
        existing_route = await graph.get_route(route_id)
        if not existing_route:
            await graph.create_route(route_data)
            await graph.link_created_route(user, route_id)
            if node_ids:
                await graph.create_route_point_links(route_id, node_ids)
            wp_entries = []
            if coords:
                start_node = await graph.find_nearest_node(coords[0]["lat"], coords[0]["lng"])
                if start_node:
                    wp_entries.append({"point_id": start_node["id"], "role": "start", "index": 0})
                end_node = await graph.find_nearest_node(coords[-1]["lat"], coords[-1]["lng"])
                if end_node:
                    wp_entries.append({"point_id": end_node["id"], "role": "end", "index": 1})
            if wp_entries:
                await graph.create_waypoint_links(route_id, wp_entries)
        await graph.create_simulation_route_link(sim_id, route_id)

    logger.info("Simulation %s started with %d cleaning tasks, %d road segments",
                sim_id, len(body.params.cleaning_tasks), engine._roads_total)

    return {
        **engine.state.model_dump(),
        "route_coords": engine.route_coords,
        "roads_total": engine._roads_total,
    }

@router.post("/{sim_id}/tick", response_model=SimulationState)
@limiter.limit("240/minute")
async def tick(request: Request, sim_id: str, user: str = Depends(get_current_user)):
    engine = await _get_or_restore_engine(request, sim_id)
    graph = request.app.state.graph_dao
    await engine.tick()
    await _persist_simulation(graph, engine)
    tick_num = engine.state.tick
    step_id = f"{sim_id}-s{tick_num}"
    existing_step = await graph.get_simulation_step(step_id)
    if not existing_step:
        vehicle_states = []
        for v in engine.vehicles:
            v_info = {
                "vehicle_id": v.id,
                "type": v.type.value if hasattr(v.type, 'value') else str(v.type),
                "status": v.status.value if hasattr(v.status, 'value') else str(v.status),
                "lat": v.location.lat,
                "lng": v.location.lng,
                "fuel_level": round(v.fuel_level, 1),
                "snow_loaded_m3": round(v.snow_loaded_m3, 1),
                "distance_travelled_km": round(v.distance_travelled_km, 2),
                "speed_kmh": round(v.speed_kmh, 2),
                "travel_speed_kmh": round(v.travel_speed_kmh, 2),
                "cleaning_speed_kmh": round(v.cleaning_speed_kmh, 2),
                "fuel_consumption_l_per_km": round(v.fuel_consumption_l_per_km, 4),
                "fuel_capacity_l": round(v.fuel_capacity_l, 2),
                "snow_capacity_m3": round(v.snow_capacity_m3, 2),
                "breakdown_probability": round(v.breakdown_probability, 4),
                "repair_time_min": round(v.repair_time_min, 1),
                "repair_remaining_min": round(v.repair_remaining_min, 1),
                "target_type": v.target_type,
                "target_id": v.target_id,
                "target_location": v.target_location.model_dump() if v.target_location else None,
                "road_target_location": v.road_target_location.model_dump() if v.road_target_location else None,
                "road_resume_location": v.road_resume_location.model_dump() if v.road_resume_location else None,
                "progress_m": round(v.progress_m, 2),
                "current_edge": v.current_edge,
                "current_road": v.current_road,
            }
            vehicle_states.append(v_info)
        sim_state = json.dumps({
            "tick": tick_num,
            "vehicles_active": engine.state.vehicles_active,
            "vehicles_broken": engine.state.vehicles_broken,
            "vehicles_en_route": engine.state.vehicles_en_route,
            "vehicles_cleaning": engine.state.vehicles_cleaning,
            "vehicles_dumping": engine.state.vehicles_dumping,
            "vehicles_refueling": engine.state.vehicles_refueling,
            "vehicles_maintenance": engine.state.vehicles_maintenance,
            "roads_cleaned_pct": engine.state.roads_cleaned_pct,
            "fuel_spent_l": engine.state.fuel_spent_l,
            "avg_fuel_pct": engine.state.avg_fuel_pct,
            "avg_snow_load_pct": engine.state.avg_snow_load_pct,
            "vehicles": vehicle_states,
            "events": engine._last_tick_events,
        })
        step_data = {
            "id": step_id,
            "roads_cleaned": engine.state.roads_cleaned_pct,
            "snow_collected": engine.state.snow_collected_m3,
            "fuel_spent": round(engine._total_fuel, 2),
            "breakdowns": engine._total_breakdowns,
            "tick": tick_num,
            "sim_state": sim_state,
        }
        await graph.create_simulation_step(step_data, sim_id, tick_num)
        vehicle_dicts = [v.model_dump() for v in engine.vehicles]
        await graph.create_vehicle_states(step_id, vehicle_dicts)
    return engine.state

@router.post("/{sim_id}/pause", response_model=SimulationState)
async def pause(request: Request, sim_id: str, user: str = Depends(get_current_user)):
    engine = await _get_or_restore_engine(request, sim_id)
    engine.pause()
    await _persist_simulation(request.app.state.graph_dao, engine)
    return engine.state

@router.post("/{sim_id}/resume", response_model=SimulationState)
async def resume(request: Request, sim_id: str, user: str = Depends(get_current_user)):
    engine = await _get_or_restore_engine(request, sim_id)
    engine.resume()
    await _persist_simulation(request.app.state.graph_dao, engine)
    return engine.state

@router.post("/{sim_id}/stop", response_model=SimulationState)
async def stop(request: Request, sim_id: str, user: str = Depends(get_current_user)):
    engine = await _get_or_restore_engine(request, sim_id)
    await engine.stop()
    graph = request.app.state.graph_dao
    await _persist_simulation(graph, engine)
    return engine.state

@router.get("/{sim_id}/details")
async def get_details(request: Request, sim_id: str, user: str = Depends(get_current_user)):
    if sim_id in _simulations:
        engine = _simulations[sim_id]
        return {
            **engine.state.model_dump(),
            "params": engine.params.model_dump(),
            "route_coords": engine.route_coords,
            "roads_total": engine._roads_total,
        }
    graph = request.app.state.graph_dao
    row = await graph.get_simulation(sim_id)
    if not row:
        raise HTTPException(status_code=404, detail="Simulation not found")
    params = json.loads(row.get("params_json", "{}")) if row.get("params_json") else {}
    route_coords = json.loads(row.get("route_coords_json", "[]")) if row.get("route_coords_json") else []
    return {
        **_node_to_state_dict(row),
        "params": params,
        "route_coords": route_coords,
        "roads_total": row.get("roads_total", 0),
    }

@router.get("/{sim_id}", response_model=SimulationState)
async def get_state(request: Request, sim_id: str, user: str = Depends(get_current_user)):
    if sim_id in _simulations:
        return _simulations[sim_id].state
    graph = request.app.state.graph_dao
    row = await graph.get_simulation(sim_id)
    if not row:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return _node_to_state_dict(row)

@router.get("/{sim_id}/vehicles")
async def get_vehicles(request: Request, sim_id: str, user: str = Depends(get_current_user)):
    engine = await _get_or_restore_engine(request, sim_id)
    return [v.model_dump() for v in engine.vehicles]

@router.get("/", response_model=dict)
async def list_simulations(
    request: Request,
    status: str | None = None,
    name: str | None = None,
    vehicles_min: int | None = None,
    vehicles_max: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user: str = Depends(get_current_user),
):
    graph = request.app.state.graph_dao
    result = await graph.get_simulations_paged(
        page=page, page_size=page_size,
        status=status, name=name, vehicles_min=vehicles_min, vehicles_max=vehicles_max,
        date_from=date_from, date_to=date_to,
    )
    in_memory_ids = {engine.sim_id for engine in _simulations.values()}
    items = result["items"]
    for engine in _simulations.values():
        s = engine.state
        sv = s.status.value if hasattr(s.status, "value") else str(s.status)
        if status and sv != status:
            continue
        if not any(item.get("id") == engine.sim_id for item in items):
            items.insert(0, s.model_dump())
    return result

@router.get("/{sim_id}/routes")
async def get_simulation_routes(request: Request, sim_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    return await graph.get_simulation_routes(sim_id)

@router.get("/{sim_id}/steps")
async def get_simulation_steps(
    request: Request, sim_id: str,
    page: int = 1, page_size: int = 20,
    tick_min: int | None = None, tick_max: int | None = None,
    user: str = Depends(get_current_user),
):
    graph = request.app.state.graph_dao
    return await graph.get_simulation_steps(sim_id, page=page, page_size=page_size, tick_min=tick_min, tick_max=tick_max)

@router.patch("/{sim_id}")
async def update_simulation(request: Request, sim_id: str, body: dict, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    if "name" not in body:
        raise HTTPException(status_code=400, detail="Only 'name' can be updated")
    existing = await graph.get_simulation(sim_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Simulation not found")
    await graph.update_simulation(sim_id, {"name": body["name"]})
    return {"status": "updated", "id": sim_id}

@router.delete("/{sim_id}", status_code=204)
async def delete_simulation(request: Request, sim_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    if sim_id in _simulations:
        del _simulations[sim_id]
    await graph.delete_simulation(sim_id)

def _node_to_state_dict(node: dict) -> dict:
    return {
        "id": node["id"],
        "name": node.get("name"),
        "status": node.get("status", "finished"),
        "tick": node.get("tick", 0),
        "elapsed_minutes": node.get("elapsed_minutes", 0),
        "vehicles_active": node.get("vehicles_active", 0),
        "vehicles_broken": node.get("vehicles_broken", 0),
        "vehicles_en_route": node.get("vehicles_en_route", 0),
        "vehicles_cleaning": node.get("vehicles_cleaning", 0),
        "vehicles_dumping": node.get("vehicles_dumping", 0),
        "vehicles_refueling": node.get("vehicles_refueling", 0),
        "vehicles_maintenance": node.get("vehicles_maintenance", 0),
        "roads_cleaned_pct": node.get("roads_cleaned_pct", 0),
        "snow_collected_m3": node.get("snow_collected_m3", 0),
        "fuel_spent_l": node.get("fuel_spent_l", 0),
        "avg_fuel_pct": node.get("avg_fuel_pct", 0),
        "avg_snow_load_pct": node.get("avg_snow_load_pct", 0),
        "streets": node.get("streets", []),
        "created_at": node.get("created_at"),
        "started_at": node.get("started_at"),
        "finished_at": node.get("finished_at"),
    }
