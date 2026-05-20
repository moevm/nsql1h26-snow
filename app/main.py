import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.dao.graph_dao import GraphDAO
from app.dao.cache_manager import CacheManager
from app.api import routes, routes_crud, objects, simulation, statistics, auth, users, import_export, simulation_steps, vehicle_states
from app.observability.telemetry import setup_telemetry
from app.observability.logger import setup_logging

logger = logging.getLogger(__name__)
settings = get_settings()

@asynccontextmanager
async def lifespan(application: FastAPI):
    setup_logging()
    logger.info("Starting Snow Cleaning Simulation…")

    application.state.graph_dao = GraphDAO(
        settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
    )
    await application.state.graph_dao.connect()
    await application.state.graph_dao.ensure_indexes()

    from app.osm_download import download_osm_if_needed
    await asyncio.to_thread(
        download_osm_if_needed, settings.geojson_path, settings.pbf_url, settings.osm_bbox
    )

    from app.osm_import import import_osm_if_needed
    await import_osm_if_needed(application.state.graph_dao, settings.geojson_path)

    from app.seed import seed_if_empty
    await seed_if_empty(application.state.graph_dao)

    application.state.cache = CacheManager(settings.redis_url)
    await application.state.cache.connect()

    logger.info("All connections established")
    yield

    await application.state.graph_dao.close()
    await application.state.cache.close()
    logger.info("Shutdown complete")

def create_app() -> FastAPI:
    app = FastAPI(
        title="Snow Cleaning Simulation API",
        description="Симуляция уборки снега в Санкт-Петербурге",
        version="1.0.0",
        lifespan=lifespan,
    )

    setup_telemetry(app)

    from app.api.rate_limit import limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
    app.include_router(routes.router, prefix="/api/routes", tags=["Routes"])
    app.include_router(routes_crud.router, prefix="/api/routes-crud", tags=["Routes CRUD"])
    app.include_router(objects.router, prefix="/api/objects", tags=["Objects"])
    app.include_router(simulation.router, prefix="/api/simulation", tags=["Simulation"])
    app.include_router(statistics.router, prefix="/api/statistics", tags=["Statistics"])
    app.include_router(users.router, prefix="/api/users", tags=["Users"])
    app.include_router(import_export.router, prefix="/api/data", tags=["Import/Export"])
    app.include_router(simulation_steps.router, prefix="/api/simulation-steps", tags=["SimulationSteps"])
    app.include_router(vehicle_states.router, prefix="/api/vehicle-states", tags=["VehicleStates"])

    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.get("/", include_in_schema=False)
    async def root():
        logger.info("Root endpoint called")
        return FileResponse("/app/static/index.html")

    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=True)
