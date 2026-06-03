from __future__ import annotations

import json
import logging
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

from app.dao.query_utils import build_filters, build_order_by, _ROUTE_SORT_MAP, _POINT_SORT_MAP, _SIM_SORT_MAP

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
                created_at: datetime(),
                updated_at: datetime()
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
        extra_where, params = build_filters([
            ("o.object_type = $obj_type",                                            "obj_type",    obj_type),
            ("toLower(coalesce(o.object_name, '')) CONTAINS toLower($name)",         "name",        name),
            ("toLower(coalesce(o.description, '')) CONTAINS toLower($description)",  "description", description),
            ("o.lat >= $lat_min",                                                    "lat_min",     lat_min),
            ("o.lat <= $lat_max",                                                    "lat_max",     lat_max),
            ("o.lng >= $lng_min",                                                    "lng_min",     lng_min),
            ("o.lng <= $lng_max",                                                    "lng_max",     lng_max),
        ], prefix="AND ")
        return await self.run_query(
            f"""
            MATCH (o:Point)
            WHERE o.object_type IS NOT NULL {extra_where}
            RETURN o.id AS id, o.object_name AS name, o.object_type AS type,
                   o.lat AS lat, o.lng AS lng, o.capacity AS capacity,
                   o.description AS description, o.created_at AS created_at, o.updated_at AS updated_at
            ORDER BY o.updated_at DESC
            """,
            **params,
        )

    async def get_map_object(self, obj_id: str) -> dict | None:
        rows = await self.run_query(
            """
            MATCH (o:Point {id: $id})
            RETURN o.id AS id, o.object_name AS name, o.object_type AS type,
                   o.lat AS lat, o.lng AS lng, o.capacity AS capacity,
                   o.description AS description, o.created_at AS created_at, o.updated_at as updated_at
            """,
            id=obj_id,
        )
        return rows[0] if rows else None

    async def update_map_object(self, obj_id: str, updates: dict) -> None:
        field_map = {"name": "object_name", "type": "object_type"}
        mapped = {field_map.get(k, k): v for k, v in updates.items()}
        set_parts = []
        params = {"id": obj_id}
        for k, v in mapped.items():
            set_parts.append(f"o.{k} = ${k}")
            params[k] = v
        set_parts.append("o.updated_at = datetime()")
        await self.run_write(
            f"MATCH (o:Point {{id: $id}}) SET {', '.join(set_parts)}",
            **params,
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
                updated_at: datetime(),
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
        where, params = build_filters([
            ("toLower(coalesce(r.label, '')) CONTAINS toLower($label)", "label",        label),
            ("r.distance_m >= $distance_min",                           "distance_min", distance_min),
            ("r.distance_m <= $distance_max",                           "distance_max", distance_max),
            ("r.created_at >= datetime($date_from)",                    "date_from",    date_from),
            ("r.created_at <= datetime($date_to)",                      "date_to",      date_to),
        ])
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
                   r.updated_at AS updated_at,
                   r.started_at AS started_at,
                   r.finished_at AS finished_at
            ORDER BY r.created_at DESC
            """,
            **params,
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
                   r.updated_at AS updated_at,
                   r.started_at AS started_at,
                   r.finished_at AS finished_at
            """,
            id=route_id,
        )
        return rows[0] if rows else None

    async def update_route(self, route_id: str, updates: dict) -> None:
        set_parts = []
        params = {"id": route_id}
        for k, v in updates.items():
            set_parts.append(f"r.{k} = ${k}")
            params[k] = v
        set_parts.append("r.updated_at = datetime()")
        await self.run_write(
            f"MATCH (r:Route {{id: $id}}) SET {', '.join(set_parts)}",
            **params,
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

    async def get_route_waypoints_paged(self, route_id: str, page: int = 1, page_size: int = 20) -> dict:
        import math
        count_rows = await self.run_query(
            "MATCH (r:Route {id: $id})-[:WAYPOINT]->(p:Point) RETURN count(p) AS total",
            id=route_id,
        )
        total = count_rows[0]["total"] if count_rows else 0
        skip = (page - 1) * page_size
        rows = await self.run_query(
            """
            MATCH (r:Route {id: $id})-[w:WAYPOINT]->(p:Point)
            RETURN p.id AS id, p.lat AS lat, p.lng AS lng,
                   p.object_name AS object_name, p.object_type AS object_type,
                   w.role AS role, w.index AS index
            ORDER BY w.index
            SKIP $skip LIMIT $page_size
            """,
            id=route_id, skip=skip, page_size=page_size,
        )
        return {"items": rows, "total": total, "page": page, "page_size": page_size,
                "total_pages": math.ceil(total / page_size) if total else 1}

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
                   r.updated_at AS updated_at,
                   r.started_at AS started_at,
                   r.finished_at AS finished_at
            """,
            id=sim_id,
        )

    async def get_simulation_routes_paged(self, sim_id: str, page: int = 1, page_size: int = 20) -> dict:
        import math
        count_rows = await self.run_query(
            "MATCH (s:Simulation {id: $id})-[:CONTAINS_ROUTE]->(r:Route) RETURN count(r) AS total",
            id=sim_id,
        )
        total = count_rows[0]["total"] if count_rows else 0
        skip = (page - 1) * page_size
        rows = await self.run_query(
            """
            MATCH (s:Simulation {id: $id})-[:CONTAINS_ROUTE]->(r:Route)
            RETURN r.id AS id, r.label AS label,
                   r.start_lat AS start_lat, r.start_lng AS start_lng,
                   r.end_lat AS end_lat, r.end_lng AS end_lng,
                   coalesce(r.streets, []) AS streets,
                   coalesce(r.distance_m, 0) AS distance_m,
                   r.path_nodes_json AS path_nodes_json,
                   r.created_at AS created_at, r.updated_at AS updated_at,
                   r.started_at AS started_at, r.finished_at AS finished_at
            ORDER BY r.created_at
            SKIP $skip LIMIT $page_size
            """,
            id=sim_id, skip=skip, page_size=page_size,
        )
        return {"items": rows, "total": total, "page": page, "page_size": page_size,
                "total_pages": math.ceil(total / page_size) if total else 1}

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
                created_at: datetime(),
                updated_at: datetime()
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
        created_at_from: str | None = None, created_at_to: str | None = None,
        updated_at_from: str | None = None, updated_at_to: str | None = None,
        vs_en_route_min: int | None = None, vs_en_route_max: int | None = None,
        vs_cleaning_min: int | None = None, vs_cleaning_max: int | None = None,
        vs_dumping_min: int | None = None, vs_dumping_max: int | None = None,
        vs_maintenance_min: int | None = None, vs_maintenance_max: int | None = None,
        avg_fuel_min: float | None = None, avg_fuel_max: float | None = None,
        avg_snow_min: float | None = None, avg_snow_max: float | None = None,
        step_own_id: str | None = None,
        roads_cleaned_min: float | None = None, roads_cleaned_max: float | None = None,
        snow_collected_min: float | None = None, snow_collected_max: float | None = None,
        fuel_spent_min: float | None = None, fuel_spent_max: float | None = None,
        breakdowns_min: int | None = None, breakdowns_max: int | None = None,
    ) -> dict:
        import math
        skip = (page - 1) * page_size

        def _ss_state(field):
            return f"toFloat(coalesce(apoc.convert.fromJsonMap(ss.sim_state).{field}, 0))"

        where, params = build_filters([
            ("toLower(ss.id) CONTAINS toLower($step_own_id)", "step_own_id",      step_own_id),
            ("toLower(s.id) CONTAINS toLower($sim_id)",       "sim_id",           sim_id),
            ("ss.tick >= $tick_min",                          "tick_min",         tick_min),
            ("ss.tick <= $tick_max",                          "tick_max",         tick_max),
            ("ss.created_at >= datetime($created_at_from)",   "created_at_from",  created_at_from),
            ("ss.created_at <= datetime($created_at_to)",     "created_at_to",    created_at_to),
            ("ss.updated_at >= datetime($updated_at_from)",   "updated_at_from",  updated_at_from),
            ("ss.updated_at <= datetime($updated_at_to)",     "updated_at_to",    updated_at_to),
            (f"{_ss_state('vehicles_en_route')} >= $vs_en_route_min",     "vs_en_route_min",    vs_en_route_min),
            (f"{_ss_state('vehicles_en_route')} <= $vs_en_route_max",     "vs_en_route_max",    vs_en_route_max),
            (f"{_ss_state('vehicles_cleaning')} >= $vs_cleaning_min",     "vs_cleaning_min",    vs_cleaning_min),
            (f"{_ss_state('vehicles_cleaning')} <= $vs_cleaning_max",     "vs_cleaning_max",    vs_cleaning_max),
            (f"{_ss_state('vehicles_dumping')} >= $vs_dumping_min",       "vs_dumping_min",     vs_dumping_min),
            (f"{_ss_state('vehicles_dumping')} <= $vs_dumping_max",       "vs_dumping_max",     vs_dumping_max),
            (f"{_ss_state('vehicles_maintenance')} >= $vs_maintenance_min", "vs_maintenance_min", vs_maintenance_min),
            (f"{_ss_state('vehicles_maintenance')} <= $vs_maintenance_max", "vs_maintenance_max", vs_maintenance_max),
            (f"{_ss_state('avg_fuel_pct')} >= $avg_fuel_min",             "avg_fuel_min",       avg_fuel_min),
            (f"{_ss_state('avg_fuel_pct')} <= $avg_fuel_max",             "avg_fuel_max",       avg_fuel_max),
            (f"{_ss_state('avg_snow_load_pct')} >= $avg_snow_min",        "avg_snow_min",       avg_snow_min),
            (f"{_ss_state('avg_snow_load_pct')} <= $avg_snow_max",        "avg_snow_max",       avg_snow_max),
            ("coalesce(ss.roads_cleaned, 0) >= $roads_cleaned_min",   "roads_cleaned_min",  roads_cleaned_min),
            ("coalesce(ss.roads_cleaned, 0) <= $roads_cleaned_max",   "roads_cleaned_max",  roads_cleaned_max),
            ("coalesce(ss.snow_collected, 0) >= $snow_collected_min", "snow_collected_min", snow_collected_min),
            ("coalesce(ss.snow_collected, 0) <= $snow_collected_max", "snow_collected_max", snow_collected_max),
            ("coalesce(ss.fuel_spent, 0) >= $fuel_spent_min",         "fuel_spent_min",     fuel_spent_min),
            ("coalesce(ss.fuel_spent, 0) <= $fuel_spent_max",         "fuel_spent_max",     fuel_spent_max),
            ("coalesce(ss.breakdowns, 0) >= $breakdowns_min",         "breakdowns_min",     breakdowns_min),
            ("coalesce(ss.breakdowns, 0) <= $breakdowns_max",         "breakdowns_max",     breakdowns_max),
        ])
        count_rows = await self.run_query(
            f"MATCH (ss:SimulationStep)-[:RUNTIME_STATS]->(s:Simulation) {where} RETURN count(ss) AS total",
            **params,
        )
        total = count_rows[0]["total"] if count_rows else 0
        rows = await self.run_query(
            f"""
            MATCH (ss:SimulationStep)-[rs:RUNTIME_STATS]->(s:Simulation)
            {where}
            RETURN ss.id AS id, ss.roads_cleaned AS roads_cleaned,
                   ss.snow_collected AS snow_collected, ss.fuel_spent AS fuel_spent,
                   ss.breakdowns AS breakdowns, ss.tick AS tick,
                   ss.created_at AS created_at,
                   ss.updated_at AS updated_at,
                   ss.sim_state AS sim_state,
                   rs.index AS step_index,
                   s.id AS simulation_id
            ORDER BY ss.tick
            SKIP $skip LIMIT $page_size
            """,
            skip=skip, page_size=page_size,
            **params,
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
                   ss.created_at AS created_at,
                   ss.updated_at AS updated_at,
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
        set_parts = []
        params = {"id": step_id}
        for k, v in filtered.items():
            set_parts.append(f"ss.{k} = ${k}")
            params[k] = v
        set_parts.append("ss.updated_at = datetime()")
        await self.run_write(
            f"MATCH (ss:SimulationStep {{id: $id}}) SET {', '.join(set_parts)}",
            **params,
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
                    current_road: $current_road,
                    created_at: datetime(),
                    updated_at: datetime()
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
                   vs.created_at AS created_at, vs.updated_at AS updated_at,
                   vd.index AS vehicle_index
            ORDER BY vd.index
            """,
            id=step_id,
        )

    async def get_step_vehicle_states_paged(self, step_id: str, page: int = 1, page_size: int = 20) -> dict:
        import math
        count_rows = await self.run_query(
            "MATCH (vs:VehicleState)-[:VEHICLE_DETAILS]->(ss:SimulationStep {id: $id}) RETURN count(vs) AS total",
            id=step_id,
        )
        total = count_rows[0]["total"] if count_rows else 0
        skip = (page - 1) * page_size
        rows = await self.run_query(
            """
            MATCH (vs:VehicleState)-[vd:VEHICLE_DETAILS]->(ss:SimulationStep {id: $id})
            RETURN coalesce(vs.machine_id, vs.id) AS id, vs.id AS snapshot_id, vs.vehicle_type AS vehicle_type, vs.status AS status,
                   vs.lat AS lat, vs.lng AS lng,
                   vs.fuel_level AS fuel_level, vs.snow_loaded_m3 AS snow_loaded_m3,
                   vs.distance_travelled_km AS distance_travelled_km,
                   vs.speed_kmh AS speed_kmh,
                   vs.travel_speed_kmh AS travel_speed_kmh,
                   vs.cleaning_speed_kmh AS cleaning_speed_kmh,
                   vs.fuel_capacity_l AS fuel_capacity_l,
                   vs.snow_capacity_m3 AS snow_capacity_m3,
                   vs.breakdown_probability AS breakdown_probability,
                   vs.repair_remaining_min AS repair_remaining_min,
                   vs.target_type AS target_type, vs.target_id AS target_id,
                   vs.progress_m AS progress_m, vs.current_edge AS current_edge,
                   vs.current_road AS current_road,
                   vs.created_at AS created_at, vs.updated_at AS updated_at,
                   vd.index AS vehicle_index
            ORDER BY vd.index
            SKIP $skip LIMIT $page_size
            """,
            id=step_id, skip=skip, page_size=page_size,
        )
        return {"items": rows, "total": total, "page": page, "page_size": page_size,
                "total_pages": math.ceil(total / page_size) if total else 1}

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
                   vs.created_at AS created_at, vs.updated_at AS updated_at,
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
                   vs.created_at AS created_at, vs.updated_at AS updated_at,
                   vd.index AS vehicle_index,
                   ss.id AS step_id, ss.tick AS tick,
                   sim.id AS simulation_id
            """,
            id=vs_id,
        )
        return rows[0] if rows else None

    async def get_vehicle_history(self, machine_id: str, page: int = 1, page_size: int = 20) -> dict:
        import math
        skip = (page - 1) * page_size
        count_rows = await self.run_query(
            """
            MATCH (vs:VehicleState)-[:VEHICLE_DETAILS]->(ss:SimulationStep)
            WHERE coalesce(vs.machine_id, vs.id) = $id
            RETURN count(vs) AS total
            """,
            id=machine_id,
        )
        total = count_rows[0]["total"] if count_rows else 0
        rows = await self.run_query(
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
                   vs.created_at AS created_at, vs.updated_at AS updated_at,
                   vs.current_road AS current_road,
                   vd.index AS vehicle_index, ss.id AS step_id, ss.tick AS tick,
                   sim.id AS simulation_id
            ORDER BY ss.tick DESC
            SKIP $skip LIMIT $page_size
            """,
            id=machine_id, skip=skip, page_size=page_size,
        )
        return {
            "items": rows, "total": total, "page": page,
            "page_size": page_size, "total_pages": math.ceil(total / page_size) if total else 1,
        }

    async def update_vehicle_state(self, vs_id: str, updates: dict) -> None:
        allowed = {
            "status", "fuel_level", "snow_loaded_m3", "current_road",
            "target_type", "target_id", "target_lat", "target_lng",
            "progress_m", "current_edge", "repair_remaining_min",
            "travel_speed_kmh", "cleaning_speed_kmh", "fuel_consumption_l_per_km",
            "fuel_capacity_l", "snow_capacity_m3", "breakdown_probability", "repair_time_min",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        set_parts = []
        params = {"id": vs_id}
        for k, v in filtered.items():
            set_parts.append(f"vs.{k} = ${k}")
            params[k] = v
        set_parts.append("vs.updated_at = datetime()")
        await self.run_write(
            f"""
            MATCH (vs:VehicleState)-[:VEHICLE_DETAILS]->(ss:SimulationStep)
            WHERE coalesce(vs.machine_id, vs.id) = $id
            WITH vs, ss
            ORDER BY ss.tick DESC
            LIMIT 1
            SET {', '.join(set_parts)}
            """,
            **params,
        )

    async def get_vehicle_states(
        self, page: int = 1, page_size: int = 20,
        step_id: str | None = None,
        sim_id: str | None = None,
        status: str | None = None,
        vehicle_type: str | None = None,
        created_at_from: str | None = None, created_at_to: str | None = None,
        updated_at_from: str | None = None, updated_at_to: str | None = None,
        lat_min: float | None = None, lat_max: float | None = None,
        lng_min: float | None = None, lng_max: float | None = None,
        fuel_min: float | None = None, fuel_max: float | None = None,
        snow_min: float | None = None, snow_max: float | None = None,
        dist_min: float | None = None, dist_max: float | None = None,
        speed_min: float | None = None, speed_max: float | None = None,
        travel_speed_min: float | None = None, travel_speed_max: float | None = None,
        cleaning_speed_min: float | None = None, cleaning_speed_max: float | None = None,
        fuel_cap_min: float | None = None, fuel_cap_max: float | None = None,
        snow_cap_min: float | None = None, snow_cap_max: float | None = None,
        breakdown_min: float | None = None, breakdown_max: float | None = None,
        repair_rem_min: float | None = None, repair_rem_max: float | None = None,
        progress_min: float | None = None, progress_max: float | None = None,
        tick_min: int | None = None, tick_max: int | None = None,
        target_type_filter: str | None = None,
        target_id_filter: str | None = None,
        source_id_filter: str | None = None,
        dest_id_filter: str | None = None,
        step_id_filter: str | None = None,
        machine_id_filter: str | None = None,
    ) -> dict:
        import math
        base_where, base_params = build_filters([
            ("toLower(ss.id) CONTAINS toLower($step_id)",                          "step_id",         step_id),
            ("toLower(ss.id) CONTAINS toLower($step_id_filter)",                   "step_id_filter",  step_id_filter),
            ("toLower(sim.id) CONTAINS toLower($sim_id)",                          "sim_id",          sim_id),
            ("vs.vehicle_type = $vehicle_type",                                    "vehicle_type",    vehicle_type),
            ("toLower(coalesce(vs.machine_id, vs.id)) CONTAINS toLower($machine_id_filter)", "machine_id_filter", machine_id_filter),
        ])
        latest_where, latest_params = build_filters([
            ("vs.status = $status",                                                "status",            status),
            ("vs.created_at >= datetime($created_at_from)",                        "created_at_from",   created_at_from),
            ("vs.created_at <= datetime($created_at_to)",                          "created_at_to",     created_at_to),
            ("vs.updated_at >= datetime($updated_at_from)",                        "updated_at_from",   updated_at_from),
            ("vs.updated_at <= datetime($updated_at_to)",                          "updated_at_to",     updated_at_to),
            ("vs.lat >= $lat_min",                                                 "lat_min",           lat_min),
            ("vs.lat <= $lat_max",                                                 "lat_max",           lat_max),
            ("vs.lng >= $lng_min",                                                 "lng_min",           lng_min),
            ("vs.lng <= $lng_max",                                                 "lng_max",           lng_max),
            ("vs.fuel_level >= $fuel_min",                                         "fuel_min",          fuel_min),
            ("vs.fuel_level <= $fuel_max",                                         "fuel_max",          fuel_max),
            ("vs.snow_loaded_m3 >= $snow_min",                                     "snow_min",          snow_min),
            ("vs.snow_loaded_m3 <= $snow_max",                                     "snow_max",          snow_max),
            ("vs.distance_travelled_km >= $dist_min",                              "dist_min",          dist_min),
            ("vs.distance_travelled_km <= $dist_max",                              "dist_max",          dist_max),
            ("vs.speed_kmh >= $speed_min",                                         "speed_min",         speed_min),
            ("vs.speed_kmh <= $speed_max",                                         "speed_max",         speed_max),
            ("vs.travel_speed_kmh >= $travel_speed_min",                           "travel_speed_min",  travel_speed_min),
            ("vs.travel_speed_kmh <= $travel_speed_max",                           "travel_speed_max",  travel_speed_max),
            ("vs.cleaning_speed_kmh >= $cleaning_speed_min",                       "cleaning_speed_min", cleaning_speed_min),
            ("vs.cleaning_speed_kmh <= $cleaning_speed_max",                       "cleaning_speed_max", cleaning_speed_max),
            ("vs.fuel_capacity_l >= $fuel_cap_min",                                "fuel_cap_min",      fuel_cap_min),
            ("vs.fuel_capacity_l <= $fuel_cap_max",                                "fuel_cap_max",      fuel_cap_max),
            ("vs.snow_capacity_m3 >= $snow_cap_min",                               "snow_cap_min",      snow_cap_min),
            ("vs.snow_capacity_m3 <= $snow_cap_max",                               "snow_cap_max",      snow_cap_max),
            ("vs.breakdown_probability >= $breakdown_min",                         "breakdown_min",     breakdown_min),
            ("vs.breakdown_probability <= $breakdown_max",                         "breakdown_max",     breakdown_max),
            ("vs.repair_remaining_min >= $repair_rem_min",                         "repair_rem_min",    repair_rem_min),
            ("vs.repair_remaining_min <= $repair_rem_max",                         "repair_rem_max",    repair_rem_max),
            ("vs.progress_m >= $progress_min",                                     "progress_min",      progress_min),
            ("vs.progress_m <= $progress_max",                                     "progress_max",      progress_max),
            ("ss2.tick >= $tick_min",                                              "tick_min",          tick_min),
            ("ss2.tick <= $tick_max",                                              "tick_max",          tick_max),
            ("toLower(coalesce(vs.target_type, '')) CONTAINS toLower($target_type_filter)", "target_type_filter", target_type_filter),
            ("toLower(coalesce(vs.target_id, '')) CONTAINS toLower($target_id_filter)",     "target_id_filter",   target_id_filter),
            ("toLower(split(coalesce(vs.current_road, ''), '->')[0]) CONTAINS toLower($source_id_filter)", "source_id_filter", source_id_filter),
            ("toLower(split(coalesce(vs.current_road, ''), '->')[1]) CONTAINS toLower($dest_id_filter)",   "dest_id_filter",   dest_id_filter),
        ], prefix="AND ")
        params = {**base_params, **latest_params}
        skip = (page - 1) * page_size
        count_rows = await self.run_query(
             f"""
             MATCH (vs:VehicleState)-[:VEHICLE_DETAILS]->(ss:SimulationStep)-[:RUNTIME_STATS]->(sim:Simulation) {base_where}
             WITH coalesce(vs.machine_id, vs.id) AS machine_id, max(ss.tick) AS latest_tick
             MATCH (vs:VehicleState)-[:VEHICLE_DETAILS]->(ss2:SimulationStep)-[:RUNTIME_STATS]->(sim2:Simulation)
             WHERE coalesce(vs.machine_id, vs.id) = machine_id AND ss2.tick = latest_tick {latest_where}
             RETURN count(machine_id) AS total
             """,
            **params,
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
                   vs.created_at AS created_at, vs.updated_at AS updated_at,
                   vd.index AS vehicle_index,
                   ss2.id AS step_id, ss2.tick AS tick, sim2.id AS simulation_id
            ORDER BY ss2.tick DESC, vd.index
            SKIP $skip LIMIT $page_size
            """,
            skip=skip, page_size=page_size,
            **params,
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
        created_at_from: str | None = None, created_at_to: str | None = None,
        updated_at_from: str | None = None, updated_at_to: str | None = None,
        capacity_min: float | None = None, capacity_max: float | None = None,
        point_id_filter: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> dict:
        import math
        specs = [
            ("toLower(p.id) CONTAINS toLower($point_id_filter)",                  "point_id_filter",  point_id_filter),
            ("toLower(coalesce(p.object_name, '')) CONTAINS toLower($object_name)", "object_name",    object_name),
            ("p.object_type = $object_type",                                      "object_type",      object_type),
            ("toLower(coalesce(p.description, '')) CONTAINS toLower($description)", "description",    description),
            ("p.lat >= $lat_min",                                                 "lat_min",          lat_min),
            ("p.lat <= $lat_max",                                                 "lat_max",          lat_max),
            ("p.lng >= $lng_min",                                                 "lng_min",          lng_min),
            ("p.lng <= $lng_max",                                                 "lng_max",          lng_max),
            ("p.created_at >= datetime($created_at_from)",                        "created_at_from",  created_at_from),
            ("p.created_at <= datetime($created_at_to)",                          "created_at_to",    created_at_to),
            ("p.updated_at >= datetime($updated_at_from)",                        "updated_at_from",  updated_at_from),
            ("p.updated_at <= datetime($updated_at_to)",                          "updated_at_to",    updated_at_to),
            ("toFloat(coalesce(p.capacity, 0)) >= $capacity_min",                 "capacity_min",     capacity_min),
            ("toFloat(coalesce(p.capacity, 0)) <= $capacity_max",                 "capacity_max",     capacity_max),
        ]
        if only_infrastructure:
            specs.append(("p.object_type IS NOT NULL", "_only_infra", True))
        where, params = build_filters(specs)
        order_by = build_order_by(sort_by, sort_order, _POINT_SORT_MAP, "ORDER BY p.object_type DESC, p.updated_at DESC")
        skip = (page - 1) * page_size
        count_rows = await self.run_query(
            f"MATCH (p:Point) {where} RETURN count(p) AS total",
            **params,
        )
        total = count_rows[0]["total"] if count_rows else 0
        rows = await self.run_query(
            f"""
            MATCH (p:Point)
            {where}
            RETURN p.id AS id, p.object_name AS object_name, p.object_type AS object_type,
                   p.lat AS lat, p.lng AS lng, p.description AS description,
                   p.capacity AS capacity, p.created_at AS created_at, p.updated_at AS updated_at,
                   CASE WHEN p.object_type IS NOT NULL THEN 'True' ELSE 'False' END AS is_infrastructure
            {order_by}
            SKIP $skip LIMIT $page_size
            """,
            skip=skip, page_size=page_size,
            **params,
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
        updated_at_from: str | None = None, updated_at_to: str | None = None,
        started_at_from: str | None = None, started_at_to: str | None = None,
        finished_at_from: str | None = None, finished_at_to: str | None = None,
        path_nodes_min: int | None = None, path_nodes_max: int | None = None,
        route_id_filter: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> dict:
        import math
        path_size = "size(apoc.convert.fromJsonList(coalesce(r.path_nodes_json, '[]')))"
        where, params = build_filters([
            ("toLower(r.id) CONTAINS toLower($route_id_filter)",        "route_id_filter",  route_id_filter),
            ("toLower(coalesce(r.label, '')) CONTAINS toLower($label)", "label",            label),
            ("r.distance_m >= $distance_min",                           "distance_min",     distance_min),
            ("r.distance_m <= $distance_max",                           "distance_max",     distance_max),
            ("r.created_at >= datetime($date_from)",                    "date_from",        date_from),
            ("r.created_at <= datetime($date_to)",                      "date_to",          date_to),
            ("r.updated_at >= datetime($updated_at_from)",              "updated_at_from",  updated_at_from),
            ("r.updated_at <= datetime($updated_at_to)",                "updated_at_to",    updated_at_to),
            ("r.started_at >= datetime($started_at_from)",              "started_at_from",  started_at_from),
            ("r.started_at <= datetime($started_at_to)",                "started_at_to",    started_at_to),
            ("r.finished_at >= datetime($finished_at_from)",            "finished_at_from", finished_at_from),
            ("r.finished_at <= datetime($finished_at_to)",              "finished_at_to",   finished_at_to),
            (f"{path_size} >= $path_nodes_min",                         "path_nodes_min",   path_nodes_min),
            (f"{path_size} <= $path_nodes_max",                         "path_nodes_max",   path_nodes_max),
        ])
        skip = (page - 1) * page_size
        order_by = build_order_by(sort_by, sort_order, _ROUTE_SORT_MAP, "ORDER BY r.updated_at DESC")
        count_rows = await self.run_query(
            f"MATCH (r:Route) {where} RETURN count(r) AS total",
            **params,
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
                   r.updated_at AS updated_at,
                   r.started_at AS started_at,
                   r.finished_at AS finished_at,
                   CASE WHEN r.path_nodes_json IS NOT NULL THEN {path_size} ELSE 0 END AS path_nodes_count
            {order_by}
            SKIP $skip LIMIT $page_size
            """,
            skip=skip, page_size=page_size,
            **params,
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
        updated_at_from: str | None = None, updated_at_to: str | None = None,
        vehicles_en_route_min: int | None = None, vehicles_en_route_max: int | None = None,
        vehicles_cleaning_min: int | None = None, vehicles_cleaning_max: int | None = None,
        vehicles_dumping_min: int | None = None, vehicles_dumping_max: int | None = None,
        vehicles_refueling_min: int | None = None, vehicles_refueling_max: int | None = None,
        vehicles_maintenance_min: int | None = None, vehicles_maintenance_max: int | None = None,
        snow_min: float | None = None, snow_max: float | None = None,
        fuel_min: float | None = None, fuel_max: float | None = None,
        avg_fuel_min: float | None = None, avg_fuel_max: float | None = None,
        avg_snow_min: float | None = None, avg_snow_max: float | None = None,
        roads_total_min: int | None = None, roads_total_max: int | None = None,
        speed_multiplier_min: float | None = None, speed_multiplier_max: float | None = None,
        tick_duration_min_min: float | None = None, tick_duration_min_max: float | None = None,
        snowfall_cm_min: float | None = None, snowfall_cm_max: float | None = None,
        refuel_threshold_min: float | None = None, refuel_threshold_max: float | None = None,
        dump_threshold_min: float | None = None, dump_threshold_max: float | None = None,
        snow_melt_rate_min: float | None = None, snow_melt_rate_max: float | None = None,
        sim_id_filter: str | None = None,
        roads_cleaned_pct_min: float | None = None, roads_cleaned_pct_max: float | None = None,
        tick_min: int | None = None, tick_max: int | None = None,
        elapsed_minutes_min: float | None = None, elapsed_minutes_max: float | None = None,
        streets_count_min: int | None = None, streets_count_max: int | None = None,
        started_at_from: str | None = None, started_at_to: str | None = None,
        finished_at_from: str | None = None, finished_at_to: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> dict:
        import math

        def _param(field):
            return (f"CASE WHEN s.params_json IS NOT NULL THEN "
                    f"toFloat(coalesce(apoc.convert.fromJsonMap(s.params_json).{field}, 0)) "
                    f"ELSE 0.0 END")

        where, params = build_filters([
            ("toLower(s.id) CONTAINS toLower($sim_id_filter)",                "sim_id_filter",            sim_id_filter),
            ("s.status = $status",                                            "status",                   status),
            ("toLower(coalesce(s.name, '')) CONTAINS toLower($name)",         "name",                     name),
            ("coalesce(s.vehicles_total, s.vehicles_active, 0) >= $vehicles_min", "vehicles_min",         vehicles_min),
            ("coalesce(s.vehicles_total, s.vehicles_active, 0) <= $vehicles_max", "vehicles_max",         vehicles_max),
            ("s.created_at >= datetime($date_from)",                          "date_from",                date_from),
            ("s.created_at <= datetime($date_to)",                            "date_to",                  date_to),
            ("s.updated_at >= datetime($updated_at_from)",                    "updated_at_from",          updated_at_from),
            ("s.updated_at <= datetime($updated_at_to)",                      "updated_at_to",            updated_at_to),
            ("coalesce(s.vehicles_en_route, 0) >= $vehicles_en_route_min",    "vehicles_en_route_min",    vehicles_en_route_min),
            ("coalesce(s.vehicles_en_route, 0) <= $vehicles_en_route_max",    "vehicles_en_route_max",    vehicles_en_route_max),
            ("coalesce(s.vehicles_cleaning, 0) >= $vehicles_cleaning_min",    "vehicles_cleaning_min",    vehicles_cleaning_min),
            ("coalesce(s.vehicles_cleaning, 0) <= $vehicles_cleaning_max",    "vehicles_cleaning_max",    vehicles_cleaning_max),
            ("coalesce(s.vehicles_dumping, 0) >= $vehicles_dumping_min",      "vehicles_dumping_min",     vehicles_dumping_min),
            ("coalesce(s.vehicles_dumping, 0) <= $vehicles_dumping_max",      "vehicles_dumping_max",     vehicles_dumping_max),
            ("coalesce(s.vehicles_refueling, 0) >= $vehicles_refueling_min",  "vehicles_refueling_min",   vehicles_refueling_min),
            ("coalesce(s.vehicles_refueling, 0) <= $vehicles_refueling_max",  "vehicles_refueling_max",   vehicles_refueling_max),
            ("coalesce(s.vehicles_maintenance, 0) >= $vehicles_maintenance_min", "vehicles_maintenance_min", vehicles_maintenance_min),
            ("coalesce(s.vehicles_maintenance, 0) <= $vehicles_maintenance_max", "vehicles_maintenance_max", vehicles_maintenance_max),
            ("coalesce(s.snow_collected_m3, 0) >= $snow_min",                 "snow_min",                 snow_min),
            ("coalesce(s.snow_collected_m3, 0) <= $snow_max",                 "snow_max",                 snow_max),
            ("coalesce(s.fuel_spent_l, 0) >= $fuel_min",                      "fuel_min",                 fuel_min),
            ("coalesce(s.fuel_spent_l, 0) <= $fuel_max",                      "fuel_max",                 fuel_max),
            ("coalesce(s.avg_fuel_pct, 0) >= $avg_fuel_min",                  "avg_fuel_min",             avg_fuel_min),
            ("coalesce(s.avg_fuel_pct, 0) <= $avg_fuel_max",                  "avg_fuel_max",             avg_fuel_max),
            ("coalesce(s.avg_snow_load_pct, 0) >= $avg_snow_min",             "avg_snow_min",             avg_snow_min),
            ("coalesce(s.avg_snow_load_pct, 0) <= $avg_snow_max",             "avg_snow_max",             avg_snow_max),
            ("coalesce(s.roads_total, 0) >= $roads_total_min",                "roads_total_min",          roads_total_min),
            ("coalesce(s.roads_total, 0) <= $roads_total_max",                "roads_total_max",          roads_total_max),
            (f"{_param('speed_multiplier')} >= $speed_multiplier_min",        "speed_multiplier_min",     speed_multiplier_min),
            (f"{_param('speed_multiplier')} <= $speed_multiplier_max",        "speed_multiplier_max",     speed_multiplier_max),
            (f"{_param('tick_duration_min')} >= $tick_duration_min_min",      "tick_duration_min_min",    tick_duration_min_min),
            (f"{_param('tick_duration_min')} <= $tick_duration_min_max",      "tick_duration_min_max",    tick_duration_min_max),
            (f"{_param('snowfall_cm')} >= $snowfall_cm_min",                  "snowfall_cm_min",          snowfall_cm_min),
            (f"{_param('snowfall_cm')} <= $snowfall_cm_max",                  "snowfall_cm_max",          snowfall_cm_max),
            (f"{_param('refuel_threshold_pct')} >= $refuel_threshold_min",    "refuel_threshold_min",     refuel_threshold_min),
            (f"{_param('refuel_threshold_pct')} <= $refuel_threshold_max",    "refuel_threshold_max",     refuel_threshold_max),
            (f"{_param('dump_threshold_pct')} >= $dump_threshold_min",        "dump_threshold_min",       dump_threshold_min),
            (f"{_param('dump_threshold_pct')} <= $dump_threshold_max",        "dump_threshold_max",       dump_threshold_max),
            (f"{_param('snow_melt_rate_m3_per_tick')} >= $snow_melt_rate_min", "snow_melt_rate_min",      snow_melt_rate_min),
            (f"{_param('snow_melt_rate_m3_per_tick')} <= $snow_melt_rate_max", "snow_melt_rate_max",      snow_melt_rate_max),
            ("coalesce(s.roads_cleaned_pct, 0) >= $roads_cleaned_pct_min",    "roads_cleaned_pct_min",    roads_cleaned_pct_min),
            ("coalesce(s.roads_cleaned_pct, 0) <= $roads_cleaned_pct_max",    "roads_cleaned_pct_max",    roads_cleaned_pct_max),
            ("coalesce(s.tick, 0) >= $tick_min",                              "tick_min",                 tick_min),
            ("coalesce(s.tick, 0) <= $tick_max",                              "tick_max",                 tick_max),
            ("coalesce(s.elapsed_minutes, 0) >= $elapsed_minutes_min",        "elapsed_minutes_min",      elapsed_minutes_min),
            ("coalesce(s.elapsed_minutes, 0) <= $elapsed_minutes_max",        "elapsed_minutes_max",      elapsed_minutes_max),
            ("size(coalesce(s.streets, [])) >= $streets_count_min",           "streets_count_min",        streets_count_min),
            ("size(coalesce(s.streets, [])) <= $streets_count_max",           "streets_count_max",        streets_count_max),
            ("s.started_at >= datetime($started_at_from)",                    "started_at_from",          started_at_from),
            ("s.started_at <= datetime($started_at_to)",                      "started_at_to",            started_at_to),
            ("s.finished_at >= datetime($finished_at_from)",                  "finished_at_from",         finished_at_from),
            ("s.finished_at <= datetime($finished_at_to)",                    "finished_at_to",           finished_at_to),
        ])
        skip = (page - 1) * page_size
        order_by = build_order_by(sort_by, sort_order, _SIM_SORT_MAP, "ORDER BY s.updated_at DESC")
        count_rows = await self.run_query(
            f"MATCH (s:Simulation) {where} RETURN count(s) AS total",
            **params,
        )
        total = count_rows[0]["total"] if count_rows else 0
        rows = await self.run_query(
            f"""
            MATCH (s:Simulation) {where}
            RETURN s.id AS id, s.name AS name, s.status AS status,
                   s.tick AS tick, s.elapsed_minutes AS elapsed_minutes,
                   coalesce(s.vehicles_total, s.vehicles_active, 0) AS vehicles_total,
                   s.vehicles_active AS vehicles_active, s.vehicles_broken AS vehicles_broken,
                   s.vehicles_en_route AS vehicles_en_route, s.vehicles_cleaning AS vehicles_cleaning,
                   s.vehicles_dumping AS vehicles_dumping, s.vehicles_refueling AS vehicles_refueling,
                   s.vehicles_maintenance AS vehicles_maintenance,
                   s.roads_cleaned_pct AS roads_cleaned_pct, s.snow_collected_m3 AS snow_collected_m3,
                   s.fuel_spent_l AS fuel_spent_l, s.avg_fuel_pct AS avg_fuel_pct,
                   s.avg_snow_load_pct AS avg_snow_load_pct,
                   coalesce(s.streets, []) AS streets,
                   s.roads_total AS roads_total,
                   s.created_at AS created_at,
                   s.updated_at AS updated_at,
                   s.started_at AS started_at, s.finished_at AS finished_at,
                   s.params_json AS params_json
            {order_by}
            SKIP $skip LIMIT $page_size
            """,
            skip=skip, page_size=page_size,
            **params,
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
                updated_at: datetime(),
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
        set_parts = []
        params = {"id": sim_id}
        for k, v in updates.items():
            set_parts.append(f"s.{k} = ${k}")
            params[k] = v
        set_parts.append("s.updated_at = datetime()")
        await self.run_write(
            f"MATCH (s:Simulation {{id: $id}}) SET {', '.join(set_parts)}",
            **params,
        )

    async def get_simulations(self, status: str | None = None, vehicles_min: int | None = None,
                               vehicles_max: int | None = None, date_from: str | None = None,
                               date_to: str | None = None) -> list[dict]:
        where, params = build_filters([
            ("s.status = $status",                       "status",       status),
            ("s.vehicles_active >= $vehicles_min",       "vehicles_min", vehicles_min),
            ("s.vehicles_active <= $vehicles_max",       "vehicles_max", vehicles_max),
            ("s.created_at >= datetime($date_from)",     "date_from",    date_from),
            ("s.created_at <= datetime($date_to)",       "date_to",      date_to),
        ])
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
                   s.updated_at AS updated_at,
                   s.started_at AS started_at, s.finished_at AS finished_at
            ORDER BY s.updated_at DESC
            """,
            **params,
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
                   s.updated_at AS updated_at,
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
                created_at: datetime(), updated_at: datetime()
            })
            """,
            id=user["id"], name=user["name"], password_hash=user["password_hash"],
            role=user.get("role", "operator"),
        )

    async def get_users(
        self, name: str | None = None,
        created_at_from: str | None = None, created_at_to: str | None = None,
        updated_at_from: str | None = None, updated_at_to: str | None = None,
        user_id: str | None = None, role: str | None = None,
        page: int = 1, page_size: int = 20,
    ) -> dict:
        import math
        where, params = build_filters([
            ("toLower(u.id) CONTAINS toLower($user_id)",     "user_id",          user_id),
            ("toLower(u.name) CONTAINS toLower($name)",      "name",             name),
            ("u.role = $role",                               "role",             role),
            ("u.created_at >= datetime($created_at_from)",   "created_at_from",  created_at_from),
            ("u.created_at <= datetime($created_at_to)",     "created_at_to",    created_at_to),
            ("u.updated_at >= datetime($updated_at_from)",   "updated_at_from",  updated_at_from),
            ("u.updated_at <= datetime($updated_at_to)",     "updated_at_to",    updated_at_to),
        ])
        skip = (page - 1) * page_size
        count_rows = await self.run_query(
            f"MATCH (u:User) {where} RETURN count(u) AS total", **params
        )
        total = count_rows[0]["total"] if count_rows else 0
        rows = await self.run_query(
            f"""
            MATCH (u:User)
            {where}
            RETURN u.id AS id, u.name AS name, coalesce(u.role, 'operator') AS role,
                   u.created_at AS created_at, u.updated_at AS updated_at
            ORDER BY u.created_at DESC
            SKIP $skip LIMIT $page_size
            """,
            skip=skip, page_size=page_size, **params,
        )
        return {
            "items": rows, "total": total, "page": page,
            "page_size": page_size, "total_pages": math.ceil(total / page_size) if total else 1,
        }

    async def get_user_by_name(self, name: str) -> dict | None:
        rows = await self.run_query(
            "MATCH (u:User {name: $name}) "
            "RETURN u.id AS id, u.name AS name, "
            "coalesce(u.role, 'operator') AS role, u.password_hash AS password_hash, "
            "u.created_at AS created_at, u.updated_at AS updated_at",
            name=name,
        )
        return rows[0] if rows else None

    async def get_user(self, user_id: str) -> dict | None:
        rows = await self.run_query(
            "MATCH (u:User {id: $id}) "
            "RETURN u.id AS id, u.name AS name, "
            "coalesce(u.role, 'operator') AS role, "
            "u.created_at AS created_at, u.updated_at AS updated_at",
            id=user_id,
        )
        return rows[0] if rows else None

    async def update_user(self, user_id: str, updates: dict) -> None:
        updates["updated_at"] = "datetime()"
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
