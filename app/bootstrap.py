from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.dao.graph_dao import GraphDAO
from app.osm_download import download_osm_if_needed
from app.osm_import import import_osm_if_needed
from app.seed import seed_if_empty, import_json

logger = logging.getLogger(__name__)

async def bootstrap() -> None:
    settings = get_settings()
    if not settings.import_json:
        await asyncio.to_thread(
            download_osm_if_needed, settings.geojson_path, settings.pbf_url, settings.osm_bbox
        )
    graph = GraphDAO(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    await graph.connect()
    try:
        await graph.ensure_indexes()
        if not settings.import_json:
            await import_osm_if_needed(graph, settings.geojson_path)
            await seed_if_empty(graph)
        else:
            await import_json(graph)
        logger.info("Bootstrap complete")
    finally:
        await graph.close()

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(bootstrap())

if __name__ == "__main__":
    main()
