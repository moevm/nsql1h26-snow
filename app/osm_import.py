from __future__ import annotations

import logging
import math
from pathlib import Path
from xml.etree.ElementTree import iterparse

from app.dao.graph_dao import GraphDAO

logger = logging.getLogger(__name__)
OSM_GRAPH_VERSION = "2"

DRIVABLE_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
}

HIGHWAY_SPEED_FACTOR = {
    "motorway": 1.0,
    "motorway_link": 0.95,
    "trunk": 0.95,
    "trunk_link": 0.9,
    "primary": 0.85,
    "primary_link": 0.8,
    "secondary": 0.75,
    "secondary_link": 0.72,
    "tertiary": 0.68,
    "tertiary_link": 0.65,
    "unclassified": 0.6,
    "residential": 0.55,
    "living_street": 0.45,
    "service": 0.4,
}


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_width(tags: dict[str, str]) -> float | None:
    raw = (tags.get("width") or "").strip().lower().replace(",", ".")
    if raw.endswith("m"):
        raw = raw[:-1].strip()
    try:
        return round(float(raw), 1) if raw else None
    except ValueError:
        lanes = tags.get("lanes")
        try:
            return round(float(lanes) * 3.25, 1) if lanes else None
        except ValueError:
            return None


def _is_oneway(tags: dict[str, str]) -> bool:
    oneway = (tags.get("oneway") or "").strip().lower()
    if oneway in {"yes", "1", "true"}:
        return True
    if tags.get("junction") == "roundabout":
        return True
    return False


def _iter_osm_roads(osm_path: Path) -> tuple[dict[str, tuple[float, float]], list[dict]]:
    nodes: dict[str, tuple[float, float]] = {}
    roads: list[dict] = []

    logger.info("Parsing OSM data from %s", osm_path)
    for _, elem in iterparse(osm_path, events=("end",)):
        tag = _local_name(elem.tag)

        if tag == "node":
            node_id = elem.attrib.get("id")
            lat = elem.attrib.get("lat")
            lon = elem.attrib.get("lon")
            if node_id and lat and lon:
                nodes[node_id] = (float(lat), float(lon))
            elem.clear()
            continue

        if tag != "way":
            continue

        refs: list[str] = []
        tags: dict[str, str] = {}
        for child in elem:
            child_tag = _local_name(child.tag)
            if child_tag == "nd":
                ref = child.attrib.get("ref")
                if ref:
                    refs.append(ref)
            elif child_tag == "tag":
                key = child.attrib.get("k")
                value = child.attrib.get("v")
                if key and value:
                    tags[key] = value

        highway = tags.get("highway")
        if highway not in DRIVABLE_HIGHWAYS or len(refs) < 2:
            elem.clear()
            continue

        oneway = _is_oneway(tags)
        name = tags.get("name")
        width_m = _parse_width(tags)
        speed_factor = HIGHWAY_SPEED_FACTOR.get(highway, 0.5)

        for src_id, dst_id in zip(refs, refs[1:]):
            src = nodes.get(src_id)
            dst = nodes.get(dst_id)
            if not src or not dst:
                continue
            distance = round(_haversine_m(src[0], src[1], dst[0], dst[1]), 1)
            if distance <= 0:
                continue

            geometry = [[src[0], src[1]], [dst[0], dst[1]]]
            roads.append(
                {
                    "src": src_id,
                    "dst": dst_id,
                    "distance": distance,
                    "name": name,
                    "highway": highway,
                    "oneway": oneway,
                    "geometry": geometry,
                    "width_m": width_m,
                    "speed_factor": speed_factor,
                }
            )
            if not oneway:
                roads.append(
                    {
                        "src": dst_id,
                        "dst": src_id,
                        "distance": distance,
                        "name": name,
                        "highway": highway,
                        "oneway": False,
                        "geometry": list(reversed(geometry)),
                        "width_m": width_m,
                        "speed_factor": speed_factor,
                    }
                )

        elem.clear()

    used_node_ids = {road["src"] for road in roads} | {road["dst"] for road in roads}
    used_nodes = {node_id: nodes[node_id] for node_id in used_node_ids if node_id in nodes}
    return used_nodes, roads


async def import_osm_if_needed(graph: GraphDAO, osm_path: str | Path) -> bool:
    road_rows = await graph.run_query("MATCH ()-[r:ROAD]->() RETURN count(r) AS total")
    road_count = road_rows[0]["total"] if road_rows else 0
    seed_rows = await graph.run_query(
        """
        MATCH (p:Point)
        WHERE p.id STARTS WITH 'seed-'
        RETURN count(p) AS total
        """
    )
    seed_point_count = seed_rows[0]["total"] if seed_rows else 0
    meta_rows = await graph.run_query(
        """
        MATCH (m:AppMeta {key: 'osm_graph_version'})
        RETURN m.value AS value
        """
    )
    graph_version = meta_rows[0]["value"] if meta_rows else None

    if road_count > 0 and seed_point_count == 0 and graph_version == OSM_GRAPH_VERSION:
        logger.info("Graph already contains imported OSM roads (%d), skipping OSM import", road_count)
        return False

    if road_count > 0 and (seed_point_count > 0 or graph_version != OSM_GRAPH_VERSION):
        logger.info("Replacing legacy road graph with OSM import")
        await graph.run_write("MATCH (vs:VehicleState) DETACH DELETE vs")
        await graph.run_write("MATCH (ss:SimulationStep) DETACH DELETE ss")
        await graph.run_write("MATCH (s:Simulation) DETACH DELETE s")
        await graph.run_write("MATCH (r:Route) DETACH DELETE r")
        await graph.run_write("MATCH ()-[rel:ROAD]->() DELETE rel")
        await graph.run_write(
            """
            MATCH (p:Point)
            WHERE p.object_type IS NULL
            DETACH DELETE p
            """
        )

    path = Path(osm_path)
    if not path.exists():
        logger.warning("OSM file %s not found, skipping OSM import", path)
        return False

    nodes, roads = _iter_osm_roads(path)
    if not roads:
        logger.warning("No drivable roads found in %s", path)
        return False

    await graph.bulk_upsert_intersections(
        [{"id": node_id, "lat": lat, "lng": lng} for node_id, (lat, lng) in nodes.items()]
    )
    await graph.bulk_upsert_roads(roads)
    await graph.run_write(
        """
        MERGE (m:AppMeta {key: 'osm_graph_version'})
        SET m.value = $value, m.updated_at = datetime()
        """,
        value=OSM_GRAPH_VERSION,
    )
    logger.info("Imported %d OSM intersections and %d ROAD relations", len(nodes), len(roads))
    return True
