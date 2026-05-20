from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.dao.graph_dao import GraphDAO
from app.osm_import import import_osm_if_needed
from app.seed import seed_if_empty

logger = logging.getLogger(__name__)

async def bootstrap() -> None:
    settings = get_settings()
    graph = GraphDAO(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    await graph.connect()
    try:
        await graph.ensure_indexes()
        await import_osm_if_needed(graph, settings.geojson_path)
        await seed_if_empty(graph)
        logger.info("Bootstrap complete")
    finally:
        await graph.close()

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(bootstrap())

if __name__ == "__main__":
    main()
