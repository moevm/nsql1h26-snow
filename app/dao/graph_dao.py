from __future__ import annotations

import json
import logging
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

class GraphDAO:

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        self._driver = AsyncGraphDatabase.driver(
            self._uri, auth=(self._user, self._password)
        )
        async with self._driver.session() as session:
            await session.run("RETURN 1")
        logger.info("Connected to Neo4j at %s", self._uri)

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            logger.info("Neo4j connection closed")

    @property
    def driver(self) -> AsyncDriver:
        assert self._driver is not None, "GraphDAO not connected"
        return self._driver

    @staticmethod
    def _coerce_neo4j_types(value: Any) -> Any:
        if hasattr(value, "to_native"):
            return value.to_native()
        if isinstance(value, list):
            return [GraphDAO._coerce_neo4j_types(v) for v in value]
        if isinstance(value, dict):
            return {k: GraphDAO._coerce_neo4j_types(v) for k, v in value.items()}
        return value

    async def run_query(self, query: str, **params: Any) -> list[dict]:
        async with self.driver.session() as session:
            result = await session.run(query, **params)
            rows = [record.data() async for record in result]
        return [{k: self._coerce_neo4j_types(v) for k, v in row.items()} for row in rows]

    async def run_write(self, query: str, **params: Any) -> Any:
        async with self.driver.session() as session:
            result = await session.run(query, **params)
            summary = await result.consume()
            return summary.counters

    async def ensure_indexes(self) -> None:
        queries = [
            "CREATE INDEX IF NOT EXISTS FOR (n:Point) ON (n.id)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Point) ON (n.lat, n.lng)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Point) ON (n.object_type)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Route) ON (n.id)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Simulation) ON (n.id)",
            "CREATE INDEX IF NOT EXISTS FOR (n:SimulationStep) ON (n.id)",
            "CREATE INDEX IF NOT EXISTS FOR (n:VehicleState) ON (n.id)",
            "CREATE INDEX IF NOT EXISTS FOR (n:User) ON (n.id)",
            "CREATE INDEX IF NOT EXISTS FOR (n:User) ON (n.name)",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Point) REQUIRE n.neo4jImportId IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Route) REQUIRE n.neo4jImportId IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Simulation) REQUIRE n.neo4jImportId IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:User) REQUIRE n.neo4jImportId IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR(n:SimulationStep) REQUIRE n.neo4jImportId IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR(n:VehicleState) REQUIRE n.neo4jImportId IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:AppMeta) REQUIRE n.neo4jImportId IS UNIQUE"
        ]
        for q in queries:
            await self.run_write(q)
        logger.info("Neo4j indexes and constraints ensured")

    async def upsert_intersection(self, node_id: str, lat: float, lng: float) -> None:
        await self.run_write(
            """
            MERGE (n:Point {id: $id})
            SET n.lat = $lat, n.lng = $lng
            """,
            id=node_id, lat=lat, lng=lng,
        )

    async def bulk_upsert_intersections(self, nodes: list[dict]) -> None:
        if not nodes:
            return
        await self.run_write(
            """
            UNWIND $nodes AS node
            MERGE (n:Point {id: node.id})
            SET n.lat = node.lat, n.lng = node.lng
            """,
            nodes=nodes,
        )

    async def upsert_road(
        self,
        src_id: str,
        dst_id: str,
        distance: float,
        name: str | None = None,
        highway: str | None = None,
        oneway: bool = False,
        geometry: list[list[float]] | None = None,
    ) -> None:
        await self.run_write(
            """
            MATCH (a:Point {id: $src}), (b:Point {id: $dst})
            MERGE (a)-[r:ROAD]->(b)
            SET r.distance = $dist,
                r.name     = $name,
                r.highway  = $highway,
                r.oneway   = $oneway,
                r.geometry = $geometry,
                r.cleaned  = false,
                r.snow_cm  = 0.0,
                r.cleaned_m = 0.0
            """,
            src=src_id, dst=dst_id, dist=distance, name=name,
            highway=highway, oneway=oneway,
            geometry=json.dumps(geometry or [], ensure_ascii=False),
        )

    async def bulk_upsert_roads(self, roads: list[dict]) -> None:
        if not roads:
            return
        payload = [
            {
                "src": road["src"],
                "dst": road["dst"],
                "distance": road["distance"],
                "name": road.get("name"),
                "highway": road.get("highway"),
                "oneway": road.get("oneway", False),
                "geometry": json.dumps(road.get("geometry") or [], ensure_ascii=False),
            }
            for road in roads
        ]
        await self.run_write(
            """
            UNWIND $roads AS road
            MATCH (a:Point {id: road.src}), (b:Point {id: road.dst})
            MERGE (a)-[r:ROAD]->(b)
            SET r.distance = road.distance,
                r.name = road.name,
                r.highway = road.highway,
                r.oneway = road.oneway,
                r.geometry = road.geometry,
                r.cleaned = false,
                r.snow_cm = 0.0,
                r.cleaned_m = 0.0
            """,
            roads=payload,
        )

    async def find_shortest_path(
        self, start_id: str, end_id: str
    ) -> dict | None:
        rows = await self.run_query(
            """
            MATCH (a:Point {id: $start}), (b:Point {id: $end}),
                  path = shortestPath((a)-[:ROAD*..200]->(b))
            WITH path, reduce(d = 0.0, r IN relationships(path) | d + r.distance) AS dist
            RETURN [n IN nodes(path) | {id: n.id, lat: n.lat, lng: n.lng}] AS nodes,
                   dist AS distance
            ORDER BY dist
            LIMIT 1
            """,
            start=start_id, end=end_id,
        )
        return rows[0] if rows else None

    async def find_path_roads(
        self, start_id: str, end_id: str
    ) -> list[dict]:
        rows = await self.run_query(
            """
            MATCH (a:Point {id: $start}), (b:Point {id: $end}),
                  path = shortestPath((a)-[:ROAD*..200]->(b))
            WITH nodes(path) AS ns, relationships(path) AS rels
            UNWIND range(0, size(rels)-1) AS i
            WITH ns[i] AS src, ns[i+1] AS dst, rels[i] AS r
            RETURN src.id AS src, dst.id AS dst,
                   src.lat AS src_lat, src.lng AS src_lng,
                   dst.lat AS dst_lat, dst.lng AS dst_lng,
                   r.distance AS distance, r.name AS name
            """,
            start=start_id, end=end_id,
        )
        return rows

    async def find_nearest_node(self, lat: float, lng: float) -> dict | None:
        rows = await self.run_query(
            """
            MATCH (n:Point)
            WHERE n.object_type IS NULL
            WITH n, point.distance(
                point({latitude: n.lat, longitude: n.lng}),
                point({latitude: $lat, longitude: $lng})
            ) AS dist
            ORDER BY dist
            LIMIT 1
            RETURN n.id AS id, n.lat AS lat, n.lng AS lng, dist AS distance
            """,
            lat=lat, lng=lng,
        )
        return rows[0] if rows else None

    async def create_map_object(self, obj: dict) -> None:
        await self.run_write(
            """
            CREATE (o:Point {
                id: $id, object_name: $object_name, object_type: $object_type,
                lat: $lat, lng: $lng,
                capacity: $capacity, description: $description,
                created_at: datetime()
            })
            """,
            id=obj["id"],
            object_name=obj.get("name") or obj.get("object_name"),
            object_type=obj.get("type") or obj.get("object_type"),
            lat=obj["lat"],
            lng=obj["lng"],
            capacity=obj.get("capacity"),
            description=obj.get("description"),
        )

    async def get_map_objects(self, obj_type: str | None = None, name: str | None = None, description: str | None = None,
                               lat_min: float | None = None, lat_max: float | None = None,
                               lng_min: float | None = None, lng_max: float | None = None) -> list[dict]:
        conditions = ["o.object_type IS NOT NULL"]
        if obj_type:
            conditions.append("o.object_type = $obj_type")
        if name:
            conditions.append("toLower(coalesce(o.object_name, '')) CONTAINS toLower($name)")
        if description:
            conditions.append("toLower(coalesce(o.description, '')) CONTAINS toLower($description)")
        if lat_min is not None:
            conditions.append("o.lat >= $lat_min")
        if lat_max is not None:
            conditions.append("o.lat <= $lat_max")
        if lng_min is not None:
            conditions.append("o.lng >= $lng_min")
        if lng_max is not None:
            conditions.append("o.lng <= $lng_max")
        where = " AND ".join(conditions)
        return await self.run_query(
            f"""
            MATCH (o:Point)
            WHERE {where}
            RETURN o.id AS id, o.object_name AS name, o.object_type AS type,
                   o.lat AS lat, o.lng AS lng, o.capacity AS capacity,
                   o.description AS description, o.created_at AS created_at
            ORDER BY o.created_at DESC
            """,
            obj_type=obj_type, name=name, description=description,
            lat_min=lat_min, lat_max=lat_max, lng_min=lng_min, lng_max=lng_max,
        )

    async def get_map_object(self, obj_id: str) -> dict | None:
        rows = await self.run_query(
            """
            MATCH (o:Point {id: $id})
            RETURN o.id AS id, o.object_name AS name, o.object_type AS type,
                   o.lat AS lat, o.lng AS lng, o.capacity AS capacity,
                   o.description AS description, o.created_at AS created_at
            """,
            id=obj_id,
        )
        return rows[0] if rows else None

    async def update_map_object(self, obj_id: str, updates: dict) -> None:
        field_map = {"name": "object_name", "type": "object_type"}
        mapped = {field_map.get(k, k): v for k, v in updates.items()}
        set_clauses = ", ".join(f"o.{k} = ${k}" for k in mapped)
        await self.run_write(
            f"MATCH (o:Point {{id: $id}}) SET {set_clauses}",
            id=obj_id, **mapped,
        )

    async def delete_map_object(self, obj_id: str) -> None:
        await self.run_write(
            "MATCH (o:Point {id: $id}) DETACH DELETE o", id=obj_id
        )

    async def mark_road_cleaned(self, src_id: str, dst_id: str) -> None:
        await self.run_write(
            """
            MATCH (a:Point {id: $src})-[r:ROAD]->(b:Point {id: $dst})
            SET r.cleaned = true,
                r.snow_cm = 0.0,
                r.cleaned_m = coalesce(r.distance, coalesce(r.cleaned_m, 0.0))
            """,
            src=src_id, dst=dst_id,
        )

    async def get_road_state(self, src_id: str, dst_id: str) -> dict | None:
        result = await self.run_query(
            """
            MATCH (a:Point {id: $src})-[r:ROAD]->(b:Point {id: $dst})
            RETURN r.cleaned AS cleaned,
                   coalesce(r.distance, 0.0) AS distance,
                   coalesce(r.cleaned_m, 0.0) AS cleaned_m,
                   coalesce(r.snow_cm, 0.0) AS snow_cm
            """,
            src=src_id, dst=dst_id,
        )
        return result[0] if result else None

    async def update_road_cleaning_progress(self, src_id: str, dst_id: str, cleaned_m: float) -> None:
        await self.run_write(
            """
            MATCH (a:Point {id: $src})-[r:ROAD]->(b:Point {id: $dst})
            SET r.cleaned_m = CASE
                    WHEN $cleaned_m > coalesce(r.cleaned_m, 0.0) THEN $cleaned_m
                    ELSE coalesce(r.cleaned_m, 0.0)
                END,
                r.cleaned = CASE
                    WHEN $cleaned_m + 0.1 >= coalesce(r.distance, 0.0) THEN true
                    ELSE coalesce(r.cleaned, false)
                END,
                r.snow_cm = CASE
                    WHEN $cleaned_m + 0.1 >= coalesce(r.distance, 0.0) THEN 0.0
                    ELSE coalesce(r.snow_cm, 0.0)
                END
            """,
            src=src_id, dst=dst_id, cleaned_m=cleaned_m,
        )

    async def is_road_cleaned(self, src_id: str, dst_id: str) -> bool:
        result = await self.run_query(
            """
            MATCH (a:Point {id: $src})-[r:ROAD]->(b:Point {id: $dst})
            RETURN r.cleaned AS cleaned,
                   coalesce(r.cleaned_m, 0.0) AS cleaned_m,
                   coalesce(r.distance, 0.0) AS distance
            """,
            src=src_id, dst=dst_id,
        )
        if not result:
            return False
        row = result[0]
        return bool(row.get("cleaned", False) or row.get("cleaned_m", 0.0) + 0.1 >= row.get("distance", 0.0))

    async def reset_snow(self, snow_cm: float) -> None:
        await self.run_write(
            "MATCH ()-[r:ROAD]->() SET r.cleaned = false, r.snow_cm = $snow, r.cleaned_m = 0.0",
            snow=snow_cm,
        )

    async def reset_snow_on_roads(self, road_pairs: list[tuple[str, str]], snow_cm: float) -> None:
        for src, dst in road_pairs:
            await self.run_write(
                """
                MATCH (a:Point {id: $src})-[r:ROAD]->(b:Point {id: $dst})
                SET r.cleaned = false, r.snow_cm = $snow, r.cleaned_m = 0.0
                """,
                src=src, dst=dst, snow=snow_cm,
            )

    async def get_uncleaned_roads(self) -> list[dict]:
        return await self.run_query(
            """
            MATCH (a)-[r:ROAD {cleaned: false}]->(b)
            RETURN a.id AS src, b.id AS dst,
                   a.lat AS src_lat, a.lng AS src_lng,
                   b.lat AS dst_lat, b.lng AS dst_lng,
                   r.distance AS distance, r.name AS name,
                   coalesce(r.cleaned_m, 0.0) AS cleaned_m,
                   coalesce(r.snow_cm, 0.0) AS snow_cm
            """
        )

    async def get_road_graph(self) -> list[dict]:
        rows = await self.run_query(
            """
            MATCH (a:Point)-[r:ROAD]->(b:Point)
            WHERE a.object_type IS NULL AND b.object_type IS NULL
            RETURN a.id AS src, b.id AS dst,
                   a.lat AS src_lat, a.lng AS src_lng,
                   b.lat AS dst_lat, b.lng AS dst_lng,
                   r.name AS name,
                   r.distance AS distance,
                   r.cleaned AS cleaned,
                   coalesce(r.cleaned_m, 0.0) AS cleaned_m,
                   coalesce(r.snow_cm, 0.0) AS snow_cm,
                   r.geometry AS geometry
            """
        )
        for row in rows:
            geometry = row.get("geometry")
            if isinstance(geometry, str):
                try:
                    row["geometry"] = json.loads(geometry)
                except json.JSONDecodeError:
                    row["geometry"] = []
        return rows

    async def create_route(self, route: dict) -> None:
        await self.run_write(
            """
            CREATE (r:Route {
                id: $id, label: $label,
                start_lat: $start_lat, start_lng: $start_lng,
                end_lat: $end_lat, end_lng: $end_lng,
                streets: $streets, distance_m: $distance_m,
                path_nodes_json: $path_nodes_json,
                created_at: datetime(),
                started_at: null, finished_at: null
            })
            """,
            **route,
        )

    async def link_created_route(self, username: str, route_id: str) -> None:
        await self.run_write(
            """
            MATCH (u:User {name: $username}), (r:Route {id: $route_id})
            MERGE (u)-[:CREATED_ROUTE]->(r)
            """,
            username=username, route_id=route_id,
        )

    async def get_routes(self, label: str | None = None, distance_min: float | None = None,
                          distance_max: float | None = None, streets_min: int | None = None,
                          streets_max: int | None = None, date_from: str | None = None,
                          date_to: str | None = None) -> list[dict]:
        conditions = []
        if label:
            conditions.append("toLower(coalesce(r.label, '')) CONTAINS toLower($label)")
        if distance_min is not None:
            conditions.append("r.distance_m >= $distance_min")
        if distance_max is not None:
            conditions.append("r.distance_m <= $distance_max")
        if date_from:
            conditions.append("r.created_at >= datetime($date_from)")
        if date_to:
            conditions.append("r.created_at <= datetime($date_to)")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await self.run_query(
            f"""
            MATCH (r:Route)
            {where}
            RETURN r.id AS id,
                   r.label AS label,
                   r.start_lat AS start_lat,
                   r.start_lng AS start_lng,
                   r.end_lat AS end_lat,
                   r.end_lng AS end_lng,
                   r.path_nodes_json AS path_nodes_json,
                   coalesce(r.streets, []) AS streets,
                   coalesce(r.distance_m, 0) AS distance_m,
                   r.created_at AS created_at,
                   r.started_at AS started_at,
                   r.finished_at AS finished_at
            ORDER BY r.created_at DESC
            """,
            label=label, distance_min=distance_min, distance_max=distance_max,
            date_from=date_from, date_to=date_to,
        )
        if streets_min is not None:
            rows = [r for r in rows if len(r.get("streets") or []) >= streets_min]
        if streets_max is not None:
            rows = [r for r in rows if len(r.get("streets") or []) <= streets_max]
        return rows

    async def get_route(self, route_id: str) -> dict | None:
        rows = await self.run_query(
            """
            MATCH (r:Route {id: $id})
            RETURN r.id AS id,
                   r.label AS label,
                   r.start_lat AS start_lat,
                   r.start_lng AS start_lng,
                   r.end_lat AS end_lat,
                   r.end_lng AS end_lng,
                   r.path_nodes_json AS path_nodes_json,
                   coalesce(r.streets, []) AS streets,
                   coalesce(r.distance_m, 0) AS distance_m,
                   r.created_at AS created_at,
                   r.started_at AS started_at,
                   r.finished_at AS finished_at
            """,
            id=route_id,
        )
        return rows[0] if rows else None

    async def update_route(self, route_id: str, updates: dict) -> None:
        set_clauses = ", ".join(f"r.{k} = ${k}" for k in updates)
        await self.run_write(
            f"MATCH (r:Route {{id: $id}}) SET {set_clauses}",
            id=route_id, **updates,
        )

    async def delete_route(self, route_id: str) -> None:
        await self.run_write(
            "MATCH (r:Route {id: $id}) DETACH DELETE r", id=route_id
        )

    async def create_route_point_links(self, route_id: str, node_ids: list[str]) -> None:
        pairs = [{"point_id": nid, "idx": i} for i, nid in enumerate(node_ids)]
        await self.run_write(
            """
            UNWIND $pairs AS pair
            MATCH (r:Route {id: $route_id}), (p:Point {id: pair.point_id})
            CREATE (r)-[:CONTAINS_POINT {index: pair.idx}]->(p)
            """,
            route_id=route_id, pairs=pairs,
        )

    async def create_waypoint_links(self, route_id: str, waypoints: list[dict]) -> None:
        if not waypoints:
            return
        await self.run_write(
            """
            UNWIND $waypoints AS wp
            MATCH (r:Route {id: $route_id}), (p:Point {id: wp.point_id})
            MERGE (r)-[:WAYPOINT {role: wp.role, index: wp.index}]->(p)
            """,
            route_id=route_id, waypoints=waypoints,
        )

    async def get_route_waypoints(self, route_id: str) -> list[dict]:
        return await self.run_query(
            """
            MATCH (r:Route {id: $id})-[w:WAYPOINT]->(p:Point)
            RETURN p.id AS id, p.lat AS lat, p.lng AS lng,
                   p.object_name AS object_name, p.object_type AS object_type,
                   w.role AS role, w.index AS index
            ORDER BY w.index
            """,
            id=route_id,
        )

    async def add_waypoint_to_route(self, route_id: str, point_id: str, role: str, index: int) -> None:
        await self.run_write(
            """
            MATCH (r:Route {id: $route_id}), (p:Point {id: $point_id})
            CREATE (r)-[:WAYPOINT {role: $role, index: $index}]->(p)
            """,
            route_id=route_id, point_id=point_id, role=role, index=index,
        )

    async def delete_route_waypoints(self, route_id: str) -> None:
        await self.run_write(
            "MATCH (r:Route {id: $id})-[w:WAYPOINT]->() DELETE w",
            id=route_id,
        )

    async def delete_route_contains_points(self, route_id: str) -> None:
        await self.run_write(
            "MATCH (r:Route {id: $id})-[cp:CONTAINS_POINT]->() DELETE cp",
            id=route_id,
        )

    async def get_route_points(self, route_id: str) -> list[dict]:
        return await self.run_query(
            """
            MATCH (r:Route {id: $id})-[cp:CONTAINS_POINT]->(p:Point)
            RETURN p.id AS id, p.lat AS lat, p.lng AS lng,
                   p.object_name AS object_name, p.object_type AS object_type,
                   cp.index AS index
            ORDER BY cp.index
            """,
            id=route_id,
        )

    async def get_route_points_paged(self, route_id: str, page: int = 1, page_size: int = 20) -> dict:
        skip = (page - 1) * page_size
        count_rows = await self.run_query(
            "MATCH (r:Route {id: $id})-[:CONTAINS_POINT]->(p:Point) RETURN count(p) AS total",
            id=route_id,
        )
        total = count_rows[0]["total"] if count_rows else 0
        rows = await self.run_query(
            """
            MATCH (r:Route {id: $id})-[cp:CONTAINS_POINT]->(p:Point)
            RETURN p.id AS id, p.lat AS lat, p.lng AS lng,
                   p.object_name AS object_name, p.object_type AS object_type,
                   cp.index AS index
            ORDER BY cp.index
            SKIP $skip LIMIT $limit
            """,
            id=route_id, skip=skip, limit=page_size,
        )
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, -(-total // page_size)),
        }

    async def create_simulation_route_link(self, sim_id: str, route_id: str) -> None:
        await self.run_write(
            """
            MATCH (s:Simulation {id: $sim_id}), (r:Route {id: $route_id})
            MERGE (s)-[:CONTAINS_ROUTE]->(r)
            """,
            sim_id=sim_id, route_id=route_id,
        )

    async def get_simulation_routes(self, sim_id: str) -> list[dict]:
        return await self.run_query(
            """
            MATCH (s:Simulation {id: $id})-[:CONTAINS_ROUTE]->(r:Route)
            RETURN r.id AS id, r.label AS label,
                   r.start_lat AS start_lat, r.start_lng AS start_lng,
                   r.end_lat AS end_lat, r.end_lng AS end_lng,
                   coalesce(r.streets, []) AS streets,
                   coalesce(r.distance_m, 0) AS distance_m,
                   r.path_nodes_json AS path_nodes_json,
                   r.created_at AS created_at,
                   r.started_at AS started_at,
                   r.finished_at AS finished_at
            """,
            id=sim_id,
        )

    async def create_simulation_step(self, step: dict, sim_id: str, index: int) -> None:
        await self.run_write(
            """
            CREATE (ss:SimulationStep {
                id: $id,
                roads_cleaned: $roads_cleaned,
                snow_collected: $snow_collected,
                fuel_spent: $fuel_spent,
                breakdowns: $breakdowns,
                tick: $tick,
                sim_state: $sim_state,
                time_created: datetime()
            })
            WITH ss
            MATCH (s:Simulation {id: $sim_id})
            CREATE (ss)-[:RUNTIME_STATS {index: $index}]->(s)
            """,
            sim_id=sim_id, index=index,
            id=step["id"], roads_cleaned=step["roads_cleaned"],
            snow_collected=step["snow_collected"], fuel_spent=step["fuel_spent"],
            breakdowns=step["breakdowns"], tick=step["tick"],
            sim_state=step.get("sim_state"),
        )

    async def get_simulation_steps(
        self, sim_id: str = None,
        page: int = 1, page_size: int = 20,
        tick_min: int | None = None, tick_max: int | None = None,
    ) -> dict:
        import math
        skip = (page - 1) * page_size
        conditions = []
        if sim_id is not None:
            conditions.append("toLower(s.id) CONTAINS toLower($sim_id)")
        if tick_min is not None:
            conditions.append("ss.tick >= $tick_min")
        if tick_max is not None:
            conditions.append("ss.tick <= $tick_max")
        where = "WHERE " + " AND ".join(conditions)
        count_rows = await self.run_query(
            f"MATCH (ss:SimulationStep)-[:RUNTIME_STATS]->(s:Simulation) {where if conditions else ''} RETURN count(ss) AS total",
            sim_id=sim_id, tick_min=tick_min, tick_max=tick_max,
        )
        total = count_rows[0]["total"] if count_rows else 0
        rows = await self.run_query(
            f"""
            MATCH (ss:SimulationStep)-[rs:RUNTIME_STATS]->(s:Simulation)
            {where if conditions else ''}
            OPTIONAL MATCH (ss)-[rs:RUNTIME_STATS]->(sim)
            RETURN ss.id AS id, ss.roads_cleaned AS roads_cleaned,
                   ss.snow_collected AS snow_collected, ss.fuel_spent AS fuel_spent,
                   ss.breakdowns AS breakdowns, ss.tick AS tick,
                   ss.time_created AS time_created,
                   ss.sim_state AS sim_state,
                   rs.index AS step_index
            ORDER BY ss.tick
            SKIP $skip LIMIT $page_size
            """,
            sim_id=sim_id, tick_min=tick_min, tick_max=tick_max,
            skip=skip, page_size=page_size,
        )
        return {
            "items": rows, "total": total, "page": page,
            "page_size": page_size, "total_pages": math.ceil(total / page_size) if total else 1,
        }

    async def get_simulation_step(self, step_id: str) -> dict | None:
        rows = await self.run_query(
            """
            MATCH (ss:SimulationStep {id: $id})
            OPTIONAL MATCH (ss)-[rs:RUNTIME_STATS]->(sim:Simulation)
            RETURN ss.id AS id, ss.roads_cleaned AS roads_cleaned,
                   ss.snow_collected AS snow_collected, ss.fuel_spent AS fuel_spent,
                   ss.breakdowns AS breakdowns, ss.tick AS tick,
                   ss.time_created AS time_created,
                   ss.sim_state AS sim_state,
                   rs.index AS step_index,
                   sim.id AS simulation_id
            """,
            id=step_id,
        )
        return rows[0] if rows else None

    async def update_simulation_step(self, step_id: str, updates: dict) -> None:
        allowed = {"roads_cleaned", "snow_collected", "fuel_spent", "breakdowns"}
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return
        set_clauses = ", ".join(f"ss.{k} = ${k}" for k in filtered)
        await self.run_write(
            f"MATCH (ss:SimulationStep {{id: $id}}) SET {set_clauses}",
            id=step_id, **filtered,
        )

    async def delete_simulation_step(self, step_id: str) -> None:
        await self.run_write(
            "MATCH (ss:SimulationStep {id: $id}) DETACH DELETE ss", id=step_id
        )

    async def create_vehicle_states(self, step_id: str, vehicles: list[dict]) -> None:
        for idx, v in enumerate(vehicles):
            loc = v.get("location") or {}
            lat = loc.get("lat", v.get("lat", 0)) if isinstance(loc, dict) else getattr(loc, "lat", v.get("lat", 0))
            lng = loc.get("lng", v.get("lng", 0)) if isinstance(loc, dict) else getattr(loc, "lng", v.get("lng", 0))
            await self.run_write(
                """
                CREATE (vs:VehicleState {
                    id: $id,
                    machine_id: $machine_id,
                    vehicle_type: $vehicle_type,
                    status: $status,
                    lat: $lat, lng: $lng,
                    home_parking_id: $home_parking_id,
                    home_parking_lat: $home_parking_lat,
                    home_parking_lng: $home_parking_lng,
                    fuel_level: $fuel_level,
                    snow_loaded_m3: $snow_loaded_m3,
                    distance_travelled_km: $distance_travelled_km,
                    speed_kmh: $speed_kmh,
                    travel_speed_kmh: $travel_speed_kmh,
                    cleaning_speed_kmh: $cleaning_speed_kmh,
                    fuel_consumption_l_per_km: $fuel_consumption_l_per_km,
                    fuel_capacity_l: $fuel_capacity_l,
                    snow_capacity_m3: $snow_capacity_m3,
                    breakdown_probability: $breakdown_probability,
                    repair_time_min: $repair_time_min,
                    repair_remaining_min: $repair_remaining_min,
                    target_type: $target_type,
                    target_id: $target_id,
                    target_lat: $target_lat,
                    target_lng: $target_lng,
                    road_target_lat: $road_target_lat,
                    road_target_lng: $road_target_lng,
                    road_resume_lat: $road_resume_lat,
                    road_resume_lng: $road_resume_lng,
                    progress_m: $progress_m,
                    current_edge: $current_edge,
                    current_road: $current_road
                })
                WITH vs
                MATCH (ss:SimulationStep {id: $step_id})
                CREATE (vs)-[:VEHICLE_DETAILS {index: $idx}]->(ss)
                """,
                step_id=step_id, idx=idx,
                id=f"{step_id}-v{idx}",
                machine_id=v.get("id"),
                vehicle_type=v.get("type") if isinstance(v.get("type"), str) else getattr(v.get("type"), "value", str(v.get("type", ""))),
                status=v.get("status") if isinstance(v.get("status"), str) else getattr(v.get("status"), "value", str(v.get("status", ""))),
                lat=lat, lng=lng,
                home_parking_id=v.get("home_parking_id"),
                home_parking_lat=(v.get("home_parking_location") or {}).get("lat") if isinstance(v.get("home_parking_location"), dict) else getattr(v.get("home_parking_location"), "lat", None),
                home_parking_lng=(v.get("home_parking_location") or {}).get("lng") if isinstance(v.get("home_parking_location"), dict) else getattr(v.get("home_parking_location"), "lng", None),
                fuel_level=v.get("fuel_level", 0),
                snow_loaded_m3=v.get("snow_loaded_m3", 0),
                distance_travelled_km=v.get("distance_travelled_km", 0),
                speed_kmh=v.get("speed_kmh", 0),
                travel_speed_kmh=v.get("travel_speed_kmh", v.get("speed_kmh", 0)),
                cleaning_speed_kmh=v.get("cleaning_speed_kmh", v.get("speed_kmh", 0)),
                fuel_consumption_l_per_km=v.get("fuel_consumption_l_per_km", 0.4),
                fuel_capacity_l=v.get("fuel_capacity_l", 0),
                snow_capacity_m3=v.get("snow_capacity_m3", 0),
                breakdown_probability=v.get("breakdown_probability", 0),
                repair_time_min=v.get("repair_time_min", 60),
                repair_remaining_min=v.get("repair_remaining_min", 0),
                target_type=v.get("target_type"),
                target_id=v.get("target_id"),
                target_lat=(v.get("target_location") or {}).get("lat") if isinstance(v.get("target_location"), dict) else getattr(v.get("target_location"), "lat", None),
                target_lng=(v.get("target_location") or {}).get("lng") if isinstance(v.get("target_location"), dict) else getattr(v.get("target_location"), "lng", None),
                road_target_lat=(v.get("road_target_location") or {}).get("lat") if isinstance(v.get("road_target_location"), dict) else getattr(v.get("road_target_location"), "lat", None),
                road_target_lng=(v.get("road_target_location") or {}).get("lng") if isinstance(v.get("road_target_location"), dict) else getattr(v.get("road_target_location"), "lng", None),
                road_resume_lat=(v.get("road_resume_location") or {}).get("lat") if isinstance(v.get("road_resume_location"), dict) else getattr(v.get("road_resume_location"), "lat", None),
                road_resume_lng=(v.get("road_resume_location") or {}).get("lng") if isinstance(v.get("road_resume_location"), dict) else getattr(v.get("road_resume_location"), "lng", None),
                progress_m=v.get("progress_m", 0),
                current_edge=v.get("current_edge"),
                current_road=v.get("current_road"),
            )

    async def get_step_vehicle_states(self, step_id: str) -> list[dict]:
        return await self.run_query(
            """
            MATCH (vs:VehicleState)-[vd:VEHICLE_DETAILS]->(ss:SimulationStep {id: $id})
            RETURN coalesce(vs.machine_id, vs.id) AS id, vs.id AS snapshot_id, vs.vehicle_type AS vehicle_type, vs.status AS status,
                   vs.lat AS lat, vs.lng AS lng,
                   vs.home_parking_id AS home_parking_id,
                   vs.home_parking_lat AS home_parking_lat,
                   vs.home_parking_lng AS home_parking_lng,
                   vs.fuel_level AS fuel_level, vs.snow_loaded_m3 AS snow_loaded_m3,
                   vs.distance_travelled_km AS distance_travelled_km,
                   vs.speed_kmh AS speed_kmh,
                   vs.travel_speed_kmh AS travel_speed_kmh,
                   vs.cleaning_speed_kmh AS cleaning_speed_kmh,
                   vs.fuel_consumption_l_per_km AS fuel_consumption_l_per_km,
                   vs.fuel_capacity_l AS fuel_capacity_l,
                   vs.snow_capacity_m3 AS snow_capacity_m3,
                   vs.breakdown_probability AS breakdown_probability,
                   vs.repair_time_min AS repair_time_min,
                   vs.repair_remaining_min AS repair_remaining_min,
                   vs.target_type AS target_type, vs.target_id AS target_id,
                   vs.target_lat AS target_lat, vs.target_lng AS target_lng,
                   vs.road_target_lat AS road_target_lat, vs.road_target_lng AS road_target_lng,
                   vs.road_resume_lat AS road_resume_lat, vs.road_resume_lng AS road_resume_lng,
                   vs.progress_m AS progress_m, vs.current_edge AS current_edge,
                   vs.current_road AS current_road,
                   vd.index AS vehicle_index
            ORDER BY vd.index
            """,
            id=step_id,
        )

    async def get_latest_simulation_vehicle_states(self, sim_id: str) -> list[dict]:
        rows = await self.run_query(
            """
            MATCH (sim:Simulation {id: $sim_id})<-[:RUNTIME_STATS]-(ss:SimulationStep)
            WITH ss
            ORDER BY ss.tick DESC
            LIMIT 1
            MATCH (vs:VehicleState)-[vd:VEHICLE_DETAILS]->(ss)
            RETURN coalesce(vs.machine_id, vs.id) AS id, vs.id AS snapshot_id, vs.vehicle_type AS vehicle_type, vs.status AS status,
                   vs.lat AS lat, vs.lng AS lng,
                   vs.home_parking_id AS home_parking_id,
                   vs.home_parking_lat AS home_parking_lat,
                   vs.home_parking_lng AS home_parking_lng,
                   vs.fuel_level AS fuel_level, vs.snow_loaded_m3 AS snow_loaded_m3,
                   vs.distance_travelled_km AS distance_travelled_km,
                   vs.speed_kmh AS speed_kmh,
                   vs.travel_speed_kmh AS travel_speed_kmh,
                   vs.cleaning_speed_kmh AS cleaning_speed_kmh,
                   vs.fuel_consumption_l_per_km AS fuel_consumption_l_per_km,
                   vs.fuel_capacity_l AS fuel_capacity_l,
                   vs.snow_capacity_m3 AS snow_capacity_m3,
                   vs.breakdown_probability AS breakdown_probability,
                   vs.repair_time_min AS repair_time_min,
                   vs.repair_remaining_min AS repair_remaining_min,
                   vs.target_type AS target_type, vs.target_id AS target_id,
                   vs.target_lat AS target_lat, vs.target_lng AS target_lng,
                   vs.road_target_lat AS road_target_lat, vs.road_target_lng AS road_target_lng,
                   vs.road_resume_lat AS road_resume_lat, vs.road_resume_lng AS road_resume_lng,
                   vs.progress_m AS progress_m, vs.current_edge AS current_edge,
                   vs.current_road AS current_road,
                   vd.index AS vehicle_index
            ORDER BY vd.index
            """,
            sim_id=sim_id,
        )
        return rows

    async def get_vehicle_state(self, vs_id: str) -> dict | None:
        rows = await self.run_query(
            """
            MATCH (vs:VehicleState)
            WHERE coalesce(vs.machine_id, vs.id) = $id
            MATCH (vs)-[vd:VEHICLE_DETAILS]->(ss:SimulationStep)-[:RUNTIME_STATS]->(sim:Simulation)
            WITH vs, vd, ss, sim
            ORDER BY ss.tick DESC
            LIMIT 1
            RETURN coalesce(vs.machine_id, vs.id) AS id, vs.id AS snapshot_id, vs.vehicle_type AS vehicle_type, vs.status AS status,
                   vs.lat AS lat, vs.lng AS lng,
                   vs.home_parking_id AS home_parking_id,
                   vs.home_parking_lat AS home_parking_lat,
                   vs.home_parking_lng AS home_parking_lng,
                   vs.fuel_level AS fuel_level, vs.snow_loaded_m3 AS snow_loaded_m3,
                   vs.distance_travelled_km AS distance_travelled_km,
                   vs.speed_kmh AS speed_kmh,
                   vs.travel_speed_kmh AS travel_speed_kmh,
                   vs.cleaning_speed_kmh AS cleaning_speed_kmh,
                   vs.fuel_consumption_l_per_km AS fuel_consumption_l_per_km,
                   vs.fuel_capacity_l AS fuel_capacity_l,
                   vs.snow_capacity_m3 AS snow_capacity_m3,
                   vs.breakdown_probability AS breakdown_probability,
                   vs.repair_time_min AS repair_time_min,
                   vs.repair_remaining_min AS repair_remaining_min,
                   vs.target_type AS target_type, vs.target_id AS target_id,
                   vs.target_lat AS target_lat, vs.target_lng AS target_lng,
                   vs.road_target_lat AS road_target_lat, vs.road_target_lng AS road_target_lng,
                   vs.road_resume_lat AS road_resume_lat, vs.road_resume_lng AS road_resume_lng,
                   vs.progress_m AS progress_m, vs.current_edge AS current_edge,
                   vs.current_road AS current_road,
                   vd.index AS vehicle_index,
                   ss.id AS step_id, ss.tick AS tick,
                   sim.id AS simulation_id
            """,
            id=vs_id,
        )
        return rows[0] if rows else None

    async def get_vehicle_history(self, machine_id: str) -> list[dict]:
        return await self.run_query(
            """
            MATCH (vs:VehicleState)-[vd:VEHICLE_DETAILS]->(ss:SimulationStep)-[:RUNTIME_STATS]->(sim:Simulation)
            WHERE coalesce(vs.machine_id, vs.id) = $id
            RETURN coalesce(vs.machine_id, vs.id) AS id, vs.id AS snapshot_id, vs.vehicle_type AS vehicle_type, vs.status AS status,
                   vs.lat AS lat, vs.lng AS lng,
                   vs.fuel_level AS fuel_level, vs.snow_loaded_m3 AS snow_loaded_m3,
                   vs.distance_travelled_km AS distance_travelled_km,
                   vs.speed_kmh AS speed_kmh,
                   vs.travel_speed_kmh AS travel_speed_kmh,
                   vs.cleaning_speed_kmh AS cleaning_speed_kmh,
                   vs.fuel_consumption_l_per_km AS fuel_consumption_l_per_km,
                   vs.fuel_capacity_l AS fuel_capacity_l,
                   vs.snow_capacity_m3 AS snow_capacity_m3,
                   vs.breakdown_probability AS breakdown_probability,
                   vs.repair_time_min AS repair_time_min,
                   vs.repair_remaining_min AS repair_remaining_min,
                   vs.target_type AS target_type, vs.target_id AS target_id,
                   vs.target_lat AS target_lat, vs.target_lng AS target_lng,
                   vs.road_target_lat AS road_target_lat, vs.road_target_lng AS road_target_lng,
                   vs.road_resume_lat AS road_resume_lat, vs.road_resume_lng AS road_resume_lng,
                   vs.progress_m AS progress_m, vs.current_edge AS current_edge,
                   vs.current_road AS current_road,
                   vd.index AS vehicle_index, ss.id AS step_id, ss.tick AS tick,
                   sim.id AS simulation_id
            ORDER BY ss.tick DESC
            """,
            id=machine_id,
        )

    async def update_vehicle_state(self, vs_id: str, updates: dict) -> None:
        allowed = {
            "status", "fuel_level", "snow_loaded_m3", "current_road",
            "target_type", "target_id", "target_lat", "target_lng",
            "progress_m", "current_edge", "repair_remaining_min",
            "travel_speed_kmh", "cleaning_speed_kmh", "fuel_consumption_l_per_km",
            "fuel_capacity_l", "snow_capacity_m3", "breakdown_probability", "repair_time_min",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return
        set_clauses = ", ".join(f"vs.{k} = ${k}" for k in filtered)
        await self.run_write(
            f"""
            MATCH (vs:VehicleState)-[:VEHICLE_DETAILS]->(ss:SimulationStep)
            WHERE coalesce(vs.machine_id, vs.id) = $id
            WITH vs, ss
            ORDER BY ss.tick DESC
            LIMIT 1
            SET {set_clauses}
            """,
            id=vs_id, **filtered,
        )

    async def get_vehicle_states(
        self, page: int = 1, page_size: int = 20,
        step_id: str | None = None,
        sim_id: str | None = None,
        status: str | None = None,
        vehicle_type: str | None = None,
    ) -> dict:
        import math
        base_conditions = []
        latest_conditions = []
        if step_id:
            base_conditions.append("toLower(ss.id) CONTAINS toLower($step_id)")
        if sim_id:
            base_conditions.append("toLower(sim.id) CONTAINS toLower($sim_id)")
        if vehicle_type:
            base_conditions.append("vs.vehicle_type = $vehicle_type")
        if status:
            latest_conditions.append("vs.status = $status")
        base_where = "WHERE " + " AND ".join(base_conditions) if base_conditions else ""
        latest_where = "AND " + " AND ".join(latest_conditions) if latest_conditions else ""
        skip = (page - 1) * page_size
        count_rows = await self.run_query(
             f"""
             MATCH (vs:VehicleState)-[:VEHICLE_DETAILS]->(ss:SimulationStep)-[:RUNTIME_STATS]->(sim:Simulation) {base_where}
             WITH coalesce(vs.machine_id, vs.id) AS machine_id, max(ss.tick) AS latest_tick
             MATCH (vs:VehicleState)-[:VEHICLE_DETAILS]->(ss2:SimulationStep)-[:RUNTIME_STATS]->(sim2:Simulation)
             WHERE coalesce(vs.machine_id, vs.id) = machine_id AND ss2.tick = latest_tick {latest_where}
             RETURN count(machine_id) AS total
             """,
            step_id=step_id, sim_id=sim_id, status=status, vehicle_type=vehicle_type,
        )
        total = count_rows[0]["total"] if count_rows else 0
        rows = await self.run_query(
            f"""
            MATCH (vs:VehicleState)-[:VEHICLE_DETAILS]->(ss:SimulationStep)-[:RUNTIME_STATS]->(sim:Simulation) {base_where}
            WITH coalesce(vs.machine_id, vs.id) AS machine_id, max(ss.tick) AS latest_tick
            MATCH (vs:VehicleState)-[vd:VEHICLE_DETAILS]->(ss2:SimulationStep)-[:RUNTIME_STATS]->(sim2:Simulation)
            WHERE coalesce(vs.machine_id, vs.id) = machine_id AND ss2.tick = latest_tick {latest_where}
            RETURN coalesce(vs.machine_id, vs.id) AS id, vs.id AS snapshot_id, vs.vehicle_type AS vehicle_type, vs.status AS status,
                   vs.lat AS lat, vs.lng AS lng,
                   vs.fuel_level AS fuel_level, vs.snow_loaded_m3 AS snow_loaded_m3,
                   vs.distance_travelled_km AS distance_travelled_km,
                   vs.speed_kmh AS speed_kmh,
                   vs.travel_speed_kmh AS travel_speed_kmh,
                   vs.cleaning_speed_kmh AS cleaning_speed_kmh,
                   vs.fuel_consumption_l_per_km AS fuel_consumption_l_per_km,
                   vs.fuel_capacity_l AS fuel_capacity_l,
                   vs.snow_capacity_m3 AS snow_capacity_m3,
                   vs.breakdown_probability AS breakdown_probability,
                   vs.repair_time_min AS repair_time_min,
                   vs.repair_remaining_min AS repair_remaining_min,
                   vs.target_type AS target_type, vs.target_id AS target_id,
                   vs.target_lat AS target_lat, vs.target_lng AS target_lng,
                   vs.road_target_lat AS road_target_lat, vs.road_target_lng AS road_target_lng,
                   vs.road_resume_lat AS road_resume_lat, vs.road_resume_lng AS road_resume_lng,
                   vs.progress_m AS progress_m, vs.current_edge AS current_edge,
                   vs.current_road AS current_road,
                   vd.index AS vehicle_index,
                   ss2.id AS step_id, ss2.tick AS tick, sim2.id AS simulation_id
            ORDER BY ss2.tick DESC, vd.index
            SKIP $skip LIMIT $page_size
            """,
            step_id=step_id, sim_id=sim_id, status=status, vehicle_type=vehicle_type,
            skip=skip, page_size=page_size,
        )
        return {
            "items": rows, "total": total, "page": page,
            "page_size": page_size, "total_pages": math.ceil(total / page_size) if total else 1,
        }

    async def get_all_points_paged(
        self, page: int = 1, page_size: int = 20,
        object_name: str | None = None,
        object_type: str | None = None,
        description: str | None = None,
        lat_min: float | None = None, lat_max: float | None = None,
        lng_min: float | None = None, lng_max: float | None = None,
        only_infrastructure: bool = False,
    ) -> dict:
        import math
        conditions = []
        if only_infrastructure:
            conditions.append("p.object_type IS NOT NULL")
        if object_name:
            conditions.append("toLower(coalesce(p.object_name, '')) CONTAINS toLower($object_name)")
        if object_type:
            conditions.append("p.object_type = $object_type")
        if description:
            conditions.append("toLower(coalesce(p.description, '')) CONTAINS toLower($description)")
        if lat_min is not None:
            conditions.append("p.lat >= $lat_min")
        if lat_max is not None:
            conditions.append("p.lat <= $lat_max")
        if lng_min is not None:
            conditions.append("p.lng >= $lng_min")
        if lng_max is not None:
            conditions.append("p.lng <= $lng_max")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        skip = (page - 1) * page_size
        count_rows = await self.run_query(
            f"MATCH (p:Point) {where} RETURN count(p) AS total",
            object_name=object_name, object_type=object_type, description=description,
            lat_min=lat_min, lat_max=lat_max, lng_min=lng_min, lng_max=lng_max,
        )
        total = count_rows[0]["total"] if count_rows else 0
        rows = await self.run_query(
            f"""
            MATCH (p:Point)
            {where}
            RETURN p.id AS id, p.object_name AS object_name, p.object_type AS object_type,
                   p.lat AS lat, p.lng AS lng, p.description AS description,
                   p.capacity AS capacity, p.created_at AS created_at
            ORDER BY p.object_type DESC, p.created_at DESC
            SKIP $skip LIMIT $page_size
            """,
            object_name=object_name, object_type=object_type, description=description,
            lat_min=lat_min, lat_max=lat_max, lng_min=lng_min, lng_max=lng_max,
            skip=skip, page_size=page_size,
        )
        return {
            "items": rows, "total": total, "page": page,
            "page_size": page_size, "total_pages": math.ceil(total / page_size) if total else 1,
        }

    async def get_routes_paged(
        self, page: int = 1, page_size: int = 20,
        label: str | None = None,
        distance_min: float | None = None, distance_max: float | None = None,
        streets_min: int | None = None, streets_max: int | None = None,
        date_from: str | None = None, date_to: str | None = None,
    ) -> dict:
        import math
        conditions = []
        if label:
            conditions.append("toLower(coalesce(r.label, '')) CONTAINS toLower($label)")
        if distance_min is not None:
            conditions.append("r.distance_m >= $distance_min")
        if distance_max is not None:
            conditions.append("r.distance_m <= $distance_max")
        if date_from:
            conditions.append("r.created_at >= datetime($date_from)")
        if date_to:
            conditions.append("r.created_at <= datetime($date_to)")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        skip = (page - 1) * page_size
        count_rows = await self.run_query(
            f"MATCH (r:Route) {where} RETURN count(r) AS total",
            label=label, distance_min=distance_min, distance_max=distance_max,
            date_from=date_from, date_to=date_to,
        )
        total = count_rows[0]["total"] if count_rows else 0
        rows = await self.run_query(
            f"""
            MATCH (r:Route)
            {where}
            RETURN r.id AS id, r.label AS label,
                   r.start_lat AS start_lat, r.start_lng AS start_lng,
                   r.end_lat AS end_lat, r.end_lng AS end_lng,
                   r.path_nodes_json AS path_nodes_json,
                   coalesce(r.streets, []) AS streets,
                   coalesce(r.distance_m, 0) AS distance_m,
                   r.created_at AS created_at,
                   r.started_at AS started_at,
                   r.finished_at AS finished_at
            ORDER BY r.created_at DESC
            SKIP $skip LIMIT $page_size
            """,
            label=label, distance_min=distance_min, distance_max=distance_max,
            date_from=date_from, date_to=date_to, skip=skip, page_size=page_size,
        )
        if streets_min is not None:
            rows = [r for r in rows if len(r.get("streets") or []) >= streets_min]
        if streets_max is not None:
            rows = [r for r in rows if len(r.get("streets") or []) <= streets_max]
        return {
            "items": rows, "total": total, "page": page,
            "page_size": page_size, "total_pages": math.ceil(total / page_size) if total else 1,
        }

    async def get_simulations_paged(
        self, page: int = 1, page_size: int = 20,
        status: str | None = None,
        name: str | None = None,
        vehicles_min: int | None = None, vehicles_max: int | None = None,
        date_from: str | None = None, date_to: str | None = None,
    ) -> dict:
        import math
        conditions = []
        if status:
            conditions.append("s.status = $status")
        if name:
            conditions.append("toLower(coalesce(s.name, '')) CONTAINS toLower($name)")
        if vehicles_min is not None:
            conditions.append("coalesce(s.vehicles_total, s.vehicles_active, 0) >= $vehicles_min")
        if vehicles_max is not None:
            conditions.append("coalesce(s.vehicles_total, s.vehicles_active, 0) <= $vehicles_max")
        if date_from:
            conditions.append("s.created_at >= datetime($date_from)")
        if date_to:
            conditions.append("s.created_at <= datetime($date_to)")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        skip = (page - 1) * page_size
        count_rows = await self.run_query(
            f"MATCH (s:Simulation) {where} RETURN count(s) AS total",
            status=status, name=name, vehicles_min=vehicles_min, vehicles_max=vehicles_max,
            date_from=date_from, date_to=date_to,
        )
        total = count_rows[0]["total"] if count_rows else 0
        rows = await self.run_query(
            f"""
            MATCH (s:Simulation) {where}
            RETURN s.id AS id, s.name AS name, s.status AS status,
                   s.tick AS tick, s.elapsed_minutes AS elapsed_minutes,
                   coalesce(s.vehicles_total, s.vehicles_active, 0) AS vehicles_total,
                   s.vehicles_active AS vehicles_active, s.vehicles_broken AS vehicles_broken,
                   s.roads_cleaned_pct AS roads_cleaned_pct, s.snow_collected_m3 AS snow_collected_m3,
                   coalesce(s.streets, []) AS streets,
                   s.roads_total AS roads_total,
                   s.created_at AS created_at,
                   s.started_at AS started_at, s.finished_at AS finished_at
            ORDER BY s.created_at DESC
            SKIP $skip LIMIT $page_size
            """,
            status=status, name=name, vehicles_min=vehicles_min, vehicles_max=vehicles_max,
            date_from=date_from, date_to=date_to, skip=skip, page_size=page_size,
        )
        return {
            "items": rows, "total": total, "page": page,
            "page_size": page_size, "total_pages": math.ceil(total / page_size) if total else 1,
        }

    async def create_simulation(self, sim: dict) -> None:
        await self.run_write(
            """
            CREATE (s:Simulation {
                id: $id, name: $name, status: $status,
                tick: $tick, elapsed_minutes: $elapsed_minutes,
                vehicles_total: $vehicles_total,
                vehicles_active: $vehicles_active, vehicles_broken: $vehicles_broken,
                roads_cleaned_pct: $roads_cleaned_pct, snow_collected_m3: $snow_collected_m3,
                streets: $streets, roads_total: $roads_total,
                route_coords_json: $route_coords_json, params_json: $params_json,
                created_at: datetime(),
                started_at: $started_at, finished_at: $finished_at
            })
            """,
            **sim,
        )

    async def link_created_simulation(self, username: str, sim_id: str) -> None:
        await self.run_write(
            """
            MATCH (u:User {name: $username}), (s:Simulation {id: $sim_id})
            MERGE (u)-[:CREATED_SIMULATION]->(s)
            """,
            username=username, sim_id=sim_id,
        )

    async def update_simulation(self, sim_id: str, updates: dict) -> None:
        set_clauses = ", ".join(f"s.{k} = ${k}" for k in updates)
        await self.run_write(
            f"MATCH (s:Simulation {{id: $id}}) SET {set_clauses}",
            id=sim_id, **updates,
        )

    async def get_simulations(self, status: str | None = None, vehicles_min: int | None = None,
                               vehicles_max: int | None = None, date_from: str | None = None,
                               date_to: str | None = None) -> list[dict]:
        conditions = []
        if status:
            conditions.append("s.status = $status")
        if vehicles_min is not None:
            conditions.append("s.vehicles_active >= $vehicles_min")
        if vehicles_max is not None:
            conditions.append("s.vehicles_active <= $vehicles_max")
        if date_from:
            conditions.append("s.created_at >= datetime($date_from)")
        if date_to:
            conditions.append("s.created_at <= datetime($date_to)")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await self.run_query(
            f"""
            MATCH (s:Simulation) {where}
            RETURN s.id AS id, s.status AS status,
                   s.tick AS tick, s.elapsed_minutes AS elapsed_minutes,
                   s.vehicles_active AS vehicles_active, s.vehicles_broken AS vehicles_broken,
                   s.roads_cleaned_pct AS roads_cleaned_pct, s.snow_collected_m3 AS snow_collected_m3,
                   coalesce(s.streets, []) AS streets,
                   s.roads_total AS roads_total,
                   s.created_at AS created_at,
                   s.started_at AS started_at, s.finished_at AS finished_at
            ORDER BY s.created_at DESC
            """,
            status=status, vehicles_min=vehicles_min, vehicles_max=vehicles_max,
            date_from=date_from, date_to=date_to,
        )

    async def get_simulation(self, sim_id: str) -> dict | None:
        rows = await self.run_query(
            """
            MATCH (s:Simulation {id: $id})
            RETURN s.id AS id, s.name AS name, s.status AS status,
                   s.tick AS tick, s.elapsed_minutes AS elapsed_minutes,
                   s.vehicles_active AS vehicles_active, s.vehicles_broken AS vehicles_broken,
                   s.vehicles_en_route AS vehicles_en_route,
                   s.vehicles_cleaning AS vehicles_cleaning,
                   s.vehicles_dumping AS vehicles_dumping,
                   s.vehicles_refueling AS vehicles_refueling,
                   s.vehicles_maintenance AS vehicles_maintenance,
                   s.roads_cleaned_pct AS roads_cleaned_pct, s.snow_collected_m3 AS snow_collected_m3,
                   s.fuel_spent_l AS fuel_spent_l,
                   s.avg_fuel_pct AS avg_fuel_pct,
                   s.avg_snow_load_pct AS avg_snow_load_pct,
                   coalesce(s.streets, []) AS streets,
                   s.roads_total AS roads_total,
                   s.created_at AS created_at,
                   s.started_at AS started_at, s.finished_at AS finished_at,
                   s.route_coords_json AS route_coords_json,
                   s.params_json AS params_json
            """, id=sim_id
        )
        return rows[0] if rows else None

    async def delete_simulation(self, sim_id: str) -> None:
        await self.run_write(
            "MATCH (s:Simulation {id: $id}) DETACH DELETE s", id=sim_id
        )

    async def get_road_stats(self) -> dict:
        rows = await self.run_query(
            """
            MATCH ()-[r:ROAD]->()
            RETURN count(r) AS total,
                   sum(CASE WHEN r.cleaned THEN 1 ELSE 0 END) AS cleaned,
                   sum(r.distance) AS total_distance
            """
        )
        return rows[0] if rows else {"total": 0, "cleaned": 0, "total_distance": 0}

    async def create_user(self, user: dict) -> None:
        await self.run_write(
            """
            CREATE (u:User {
                id: $id, name: $name, password_hash: $password_hash,
                role: $role,
                created_at: datetime(), updated_at: datetime(), time_updated: datetime()
            })
            """,
            id=user["id"], name=user["name"], password_hash=user["password_hash"],
            role=user.get("role", "operator"),
        )

    async def get_users(self, name: str | None = None) -> list[dict]:
        condition = ""
        if name:
            condition = "WHERE toLower(u.name) CONTAINS toLower($name)"
        return await self.run_query(
            f"""
            MATCH (u:User)
            {condition}
            RETURN u.id AS id, u.name AS name, coalesce(u.role, 'operator') AS role,
                   u.created_at AS created_at,
                   coalesce(u.time_updated, u.updated_at) AS time_updated,
                   coalesce(u.updated_at, u.time_updated) AS updated_at
            ORDER BY u.created_at DESC
            """,
            name=name,
        )

    async def get_user_by_name(self, name: str) -> dict | None:
        rows = await self.run_query(
            "MATCH (u:User {name: $name}) RETURN u.id AS id, u.name AS name, coalesce(u.role, 'operator') AS role, u.password_hash AS password_hash, u.created_at AS created_at, coalesce(u.time_updated, u.updated_at) AS time_updated, coalesce(u.updated_at, u.time_updated) AS updated_at",
            name=name,
        )
        return rows[0] if rows else None

    async def get_user(self, user_id: str) -> dict | None:
        rows = await self.run_query(
            "MATCH (u:User {id: $id}) RETURN u.id AS id, u.name AS name, coalesce(u.role, 'operator') AS role, u.created_at AS created_at, coalesce(u.time_updated, u.updated_at) AS time_updated, coalesce(u.updated_at, u.time_updated) AS updated_at",
            id=user_id,
        )
        return rows[0] if rows else None

    async def update_user(self, user_id: str, updates: dict) -> None:
        updates["updated_at"] = "datetime()"
        updates["time_updated"] = "datetime()"
        set_parts = []
        params = {"id": user_id}
        for k, v in updates.items():
            if v == "datetime()":
                set_parts.append(f"u.{k} = datetime()")
            else:
                set_parts.append(f"u.{k} = ${k}")
                params[k] = v
        await self.run_write(
            f"MATCH (u:User {{id: $id}}) SET {', '.join(set_parts)}",
            **params,
        )

    async def delete_user(self, user_id: str) -> None:
        await self.run_write("MATCH (u:User {id: $id}) DETACH DELETE u", id=user_id)

    async def export_apoc(self) -> str:
        rows = await self.run_query(
            "CALL apoc.export.json.all(null, {stream: true, useTypes: true}) YIELD data RETURN data"
        )
        return "".join(row["data"] for row in rows if row.get("data"))

    async def import_apoc(self, filename: str) -> dict:
        await self.run_write("MATCH (n) DETACH DELETE n")

        rows = await self.run_query(
            "CALL apoc.import.json($filename, {}) YIELD nodes, relationships, properties RETURN nodes, relationships, properties",
            filename=filename,
        )
        return rows[0] if rows else {"nodes": 0, "relationships": 0, "properties": 0}
