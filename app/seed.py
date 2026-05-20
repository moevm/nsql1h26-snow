"""Seed database with test data if empty."""
from __future__ import annotations

import json
import logging
import uuid

from app.dao.graph_dao import GraphDAO
from app.seed_data import (
    get_seed_graph,
    get_seed_map_objects,
    get_seed_routes,
    get_seed_simulations,
)

logger = logging.getLogger(__name__)
SEED_DEMO_VERSION = "2"


def _serialize_json_field(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _path_json(path_nodes: list[dict]) -> str:
    return json.dumps(path_nodes, ensure_ascii=False)


async def _build_route_through_waypoints(graph: GraphDAO, ordered_coords: list[dict]) -> dict | None:
    all_nodes: list[dict] = []
    all_node_ids: list[str] = []
    all_roads: list[dict] = []
    streets: list[str] = []
    seen_streets: set[str] = set()
    total_distance = 0.0

    for idx in range(len(ordered_coords) - 1):
        start = ordered_coords[idx]
        end = ordered_coords[idx + 1]
        start_node = await graph.find_nearest_node(start["lat"], start["lng"])
        end_node = await graph.find_nearest_node(end["lat"], end["lng"])
        if not start_node or not end_node:
            return None

        path = await graph.find_shortest_path(start_node["id"], end_node["id"])
        roads = await graph.find_path_roads(start_node["id"], end_node["id"])
        if not path or not roads:
            return None

        nodes = path["nodes"]
        if all_nodes:
            nodes = nodes[1:]

        for node in nodes:
            if all_node_ids and all_node_ids[-1] == node["id"]:
                continue
            all_nodes.append({"lat": node["lat"], "lng": node["lng"]})
            all_node_ids.append(node["id"])

        all_roads.extend(roads)
        for road in roads:
            total_distance += float(road.get("distance") or 0.0)
            name = road.get("name")
            if name and name not in seen_streets:
                seen_streets.add(name)
                streets.append(name)

    return {
        "path_nodes": all_nodes,
        "node_ids": all_node_ids,
        "roads": all_roads,
        "streets": streets,
        "distance_m": round(total_distance, 1),
    }


def _route_seed_waypoints(route: dict) -> list[dict]:
    path_nodes = route.get("path_nodes") or []
    middle = path_nodes[1:-1] if len(path_nodes) > 2 else []
    ordered = [{"lat": route["start_lat"], "lng": route["start_lng"]}]
    ordered.extend({"lat": item["lat"], "lng": item["lng"]} for item in middle[:4])
    ordered.append({"lat": route["end_lat"], "lng": route["end_lng"]})
    return ordered


def _pick_route_position(path_nodes: list[dict], ratio: float) -> tuple[float, float]:
    if not path_nodes:
        return 0.0, 0.0
    idx = min(len(path_nodes) - 1, max(0, int(round((len(path_nodes) - 1) * ratio))))
    point = path_nodes[idx]
    return point["lat"], point["lng"]


def _build_vehicle_rows_for_tick(
    sim: dict,
    route_blueprints: list[dict],
    tick: int,
) -> list[dict]:
    vehicles_active = min(5, sim["vehicles_active"])
    vehicles: list[dict] = []
    for vi in range(vehicles_active):
        blueprint = route_blueprints[vi % len(route_blueprints)] if route_blueprints else None
        status = "cleaning"
        if sim["vehicles_broken"] and vi >= max(0, vehicles_active - sim["vehicles_broken"]):
            status = "broken"
        elif vi == vehicles_active - 1 and vehicles_active > 2:
            status = "idle"

        if blueprint and blueprint["path_nodes"]:
            ratio = min(1.0, (tick + vi * 2) / max(sim["tick"] + 2, 1))
            lat, lng = _pick_route_position(blueprint["path_nodes"], ratio)
            roads = blueprint["roads"]
            road_idx = min(len(roads) - 1, max(0, int(ratio * len(roads)))) if roads else 0
            current_road = roads[road_idx].get("name") if roads else blueprint["label"]
        else:
            lat = lng = 0.0
            current_road = None

        vehicles.append(
            {
                "id": f"T-{vi:04d}",
                "type": "tractor" if vi % 2 == 0 else "loader",
                "status": status,
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "fuel_level": round(max(15.0, 100.0 - tick * 1.6 - vi * 3.5), 1),
                "snow_loaded_m3": round(min(8.0, tick * 0.18 + vi * 0.4), 2),
                "distance_travelled_km": round(max(0.2, tick * 0.22 + vi * 0.35), 2),
                "current_road": current_road if status == "cleaning" else None,
            }
        )
    return vehicles


async def _seed_map_objects_if_missing(graph: GraphDAO, map_objects: list[dict]) -> None:
    existing_objects = await graph.get_map_objects()
    if existing_objects:
        return
    for obj in map_objects:
        await graph.create_map_object(obj)
    logger.info("Seeded %d infrastructure objects", len(map_objects))


async def _delete_existing_seed_demo(graph: GraphDAO) -> None:
    await graph.run_write(
        """
        MATCH (vs:VehicleState)
        WHERE vs.id STARTS WITH 'seed-s'
        DETACH DELETE vs
        """
    )
    await graph.run_write(
        """
        MATCH (ss:SimulationStep)
        WHERE ss.id STARTS WITH 'seed-s'
        DETACH DELETE ss
        """
    )
    await graph.run_write(
        """
        MATCH (s:Simulation)
        WHERE s.id STARTS WITH 'seed-'
        DETACH DELETE s
        """
    )
    await graph.run_write(
        """
        MATCH (r:Route)
        WHERE r.id STARTS WITH 'seed-'
        DETACH DELETE r
        """
    )


async def seed_if_empty(graph: GraphDAO) -> None:
    """Ensure debug users exist, then seed demo data if DB has no Point nodes."""
    await ensure_debug_users(graph)

    graph_seed = get_seed_graph()
    map_objects = get_seed_map_objects()
    routes_data = get_seed_routes()
    simulations_data = get_seed_simulations()

    snapshot_rows = await graph.run_query(
        """
        OPTIONAL MATCH (p:Point)
        WITH count(p) AS point_count
        OPTIONAL MATCH ()-[r:ROAD]->()
        WITH point_count, count(r) AS road_count
        OPTIONAL MATCH (route:Route)
        WITH point_count, road_count, count(route) AS route_count
        OPTIONAL MATCH (sim:Simulation)
        RETURN point_count, road_count, route_count, count(sim) AS simulation_count
        """
    )
    snapshot = snapshot_rows[0] if snapshot_rows else {}
    cnt = snapshot.get("point_count", 0)
    road_count = snapshot.get("road_count", 0)
    route_count = snapshot.get("route_count", 0)
    simulation_count = snapshot.get("simulation_count", 0)
    demo_rows = await graph.run_query(
        """
        OPTIONAL MATCH (r:Route)
        WHERE r.id STARTS WITH 'seed-'
        WITH count(r) AS seed_route_count
        OPTIONAL MATCH (s:Simulation)
        WHERE s.id STARTS WITH 'seed-'
        RETURN seed_route_count, count(s) AS seed_simulation_count
        """
    )
    demo_snapshot = demo_rows[0] if demo_rows else {}
    seed_route_count = demo_snapshot.get("seed_route_count", 0)
    seed_simulation_count = demo_snapshot.get("seed_simulation_count", 0)
    meta_rows = await graph.run_query(
        """
        MATCH (m:AppMeta {key: 'seed_demo_version'})
        RETURN m.value AS value
        """
    )
    seed_demo_version = meta_rows[0]["value"] if meta_rows else None

    if cnt > 0 and road_count == 0 and route_count == 0 and simulation_count == 0:
        logger.warning("Detected partial seed state — clearing demo graph and reseeding")
        await graph.run_write("MATCH (n) DETACH DELETE n")
        await ensure_debug_users(graph)
        cnt = 0

    if (seed_route_count > 0) != (seed_simulation_count > 0):
        logger.warning("Detected partial demo seed entities — cleaning seed-* routes/simulations")
        await _delete_existing_seed_demo(graph)
        seed_route_count = 0
        seed_simulation_count = 0

    if seed_route_count > 0 and seed_simulation_count > 0 and seed_demo_version != SEED_DEMO_VERSION:
        logger.info(
            "Refreshing demo seed from version %s to %s",
            seed_demo_version,
            SEED_DEMO_VERSION,
        )
        await _delete_existing_seed_demo(graph)
        seed_route_count = 0
        seed_simulation_count = 0

    await _seed_map_objects_if_missing(graph, map_objects)

    if seed_route_count > 0 and seed_simulation_count > 0:
        logger.info("Demo seed already exists (%d routes, %d simulations) — skipping seed", seed_route_count, seed_simulation_count)
        return

    if cnt > 0 and route_count == 0 and simulation_count == 0:
        logger.info("DB has %d Points (OSM) but no demo data — seeding routes/simulations only", cnt)

    if cnt == 0:
        logger.info("DB is empty — seeding test data from JSON dumps…")

        intersections = graph_seed["intersections"]
        for point in intersections:
            await graph.upsert_intersection(point["id"], point["lat"], point["lng"])

        for road in graph_seed["roads"]:
            await graph.upsert_road(
                road["src"],
                road["dst"],
                road["distance"],
                road.get("name"),
                road.get("highway"),
                road.get("oneway", False),
                road.get("geometry"),
                road.get("width_m"),
                road.get("speed_factor"),
            )
        logger.info(
            "Seeded %d Points + %d Roads from JSON",
            len(intersections),
            len(graph_seed["roads"]),
        )

    route_sources: dict[str, dict] = {}
    for route in routes_data:
        resolved = await _build_route_through_waypoints(graph, _route_seed_waypoints(route))
        if not resolved:
            logger.warning("Skipping seed route %s: path was not resolved on current graph", route["id"])
            continue

        route_record = {
            "id": route["id"],
            "label": route["label"],
            "start_lat": resolved["path_nodes"][0]["lat"],
            "start_lng": resolved["path_nodes"][0]["lng"],
            "end_lat": resolved["path_nodes"][-1]["lat"],
            "end_lng": resolved["path_nodes"][-1]["lng"],
            "streets": resolved["streets"],
            "distance_m": resolved["distance_m"],
            "path_nodes_json": _path_json(resolved["path_nodes"]),
        }
        await graph.create_route(route_record)

        if resolved["node_ids"]:
            await graph.create_route_point_links(route["id"], resolved["node_ids"])

        waypoint_links: list[dict] = []
        for idx, coord in enumerate(_route_seed_waypoints(route)):
            nearest = await graph.find_nearest_node(coord["lat"], coord["lng"])
            if not nearest:
                continue
            role = "start" if idx == 0 else ("end" if idx == len(_route_seed_waypoints(route)) - 1 else "waypoint")
            waypoint_links.append({"point_id": nearest["id"], "role": role, "index": idx})
        if waypoint_links:
            await graph.create_waypoint_links(route["id"], waypoint_links)

        route_sources[route["id"]] = {
            "id": route["id"],
            "label": route["label"],
            **resolved,
        }
    logger.info("Seeded %d Routes", len(route_sources))

    simulation_sources: list[dict] = []
    for sim in simulations_data:
        route_ids = [route_id for route_id in sim.get("route_ids", []) if route_id in route_sources]
        route_blueprints = [route_sources[route_id] for route_id in route_ids]
        streets: list[str] = []
        seen_streets: set[str] = set()
        route_coords = []
        roads_total = 0
        for blueprint in route_blueprints:
            route_coords.append(blueprint["path_nodes"])
            roads_total += len(blueprint["roads"])
            for street in blueprint["streets"]:
                if street not in seen_streets:
                    seen_streets.add(street)
                    streets.append(street)

        sim_record = {
            "id": sim["id"],
            "name": sim["name"],
            "status": sim["status"],
            "tick": sim["tick"],
            "elapsed_minutes": sim["elapsed_minutes"],
            "vehicles_active": sim["vehicles_active"],
            "vehicles_broken": sim["vehicles_broken"],
            "roads_cleaned_pct": sim["roads_cleaned_pct"],
            "snow_collected_m3": sim["snow_collected_m3"],
            "streets": streets,
            "roads_total": roads_total,
            "route_coords_json": _serialize_json_field(route_coords),
            "params_json": _serialize_json_field(sim.get("params_json", {})),
            "started_at": sim.get("started_at"),
            "finished_at": sim.get("finished_at"),
        }
        await graph.create_simulation(sim_record)
        for route_id in route_ids:
            await graph.create_simulation_route_link(sim["id"], route_id)
        simulation_sources.append({**sim_record, "route_ids": route_ids})
    logger.info("Seeded %d Simulations", len(simulation_sources))

    step_count = 0
    for sim_index, sim in enumerate(simulation_sources):
        route_blueprints = [route_sources[route_id] for route_id in sim.get("route_ids", []) if route_id in route_sources]
        road_pool = [road.get("name") or blueprint["label"] for blueprint in route_blueprints for road in blueprint["roads"]]
        if not road_pool:
            road_pool = [blueprint["label"] for blueprint in route_blueprints] or ["Аптекарский остров"]

        for tick in range(1, sim["tick"] + 1):
            step_id = f"{sim['id']}-s{tick}"
            pct = min(round(sim["roads_cleaned_pct"] * tick / sim["tick"], 2), 100.0)
            snow = round(sim["snow_collected_m3"] * tick / sim["tick"], 1)
            fuel = round((145.0 + sim_index * 17.5) * tick / sim["tick"], 2)
            breakdowns = int(sim["vehicles_broken"] * tick / sim["tick"])
            vehicles = _build_vehicle_rows_for_tick(sim, route_blueprints, tick)
            events = []
            for vehicle in vehicles:
                if vehicle["status"] == "cleaning":
                    events.append(
                        {
                            "vehicle_id": vehicle["id"],
                            "event": "segment_cleared",
                            "road": vehicle["current_road"],
                            "lat": vehicle["lat"],
                            "lng": vehicle["lng"],
                        }
                    )
                elif vehicle["status"] == "broken":
                    events.append(
                        {
                            "vehicle_id": vehicle["id"],
                            "event": "breakdown",
                            "road": vehicle["current_road"],
                            "lat": vehicle["lat"],
                            "lng": vehicle["lng"],
                        }
                    )
            sim_state = json.dumps(
                {"tick": tick, "vehicles_active": sim["vehicles_active"], "events": events, "vehicles": vehicles},
                ensure_ascii=False,
            )
            step_data = {
                "id": step_id,
                "roads_cleaned": pct,
                "snow_collected": snow,
                "fuel_spent": fuel,
                "breakdowns": breakdowns,
                "tick": tick,
                "sim_state": sim_state,
            }
            await graph.create_simulation_step(step_data, sim["id"], tick)
            step_count += 1
            await graph.create_vehicle_states(step_id, vehicles)
    logger.info("Seeded %d SimulationSteps with VehicleStates", step_count)
    await graph.run_write(
        """
        MERGE (m:AppMeta {key: 'seed_demo_version'})
        SET m.value = $value, m.updated_at = datetime()
        """,
        value=SEED_DEMO_VERSION,
    )
    logger.info("Seed complete ✓")


async def ensure_debug_users(graph: GraphDAO) -> None:
    import bcrypt

    for username, password, role in [("admin", "admin", "admin"), ("operator", "operator", "operator")]:
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        await graph.run_write(
            """
            MERGE (u:User {name: $name})
            ON CREATE SET u.id = $id, u.created_at = datetime()
            SET u.password_hash = $password_hash,
                u.role = $role,
                u.updated_at = datetime(),
                u.time_updated = datetime()
            """,
            id=str(uuid.uuid4())[:8],
            name=username,
            password_hash=hashed,
            role=role,
        )
    logger.info("Debug users ensured: admin/admin, operator/operator")
