import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import get_current_user
from app.api.rate_limit import limiter
from app.models.schemas import SimulationStats

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/{sim_id}", response_model=SimulationStats)
@limiter.limit("60/minute")
async def get_statistics(request: Request, sim_id: str, user: str = Depends(get_current_user)):
    from app.api.simulation import _simulations

    if sim_id not in _simulations:
        raise HTTPException(status_code=404, detail="Simulation not found")

    engine = _simulations[sim_id]
    return engine.get_stats()

@router.get("/{sim_id}/roads")
@limiter.limit("60/minute")
async def get_road_stats(request: Request, sim_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    stats = await graph.get_road_stats()
    total = stats.get("total", 0)
    cleaned = stats.get("cleaned", 0)
    return {
        "total_roads": total,
        "cleaned_roads": cleaned,
        "cleaned_pct": round(cleaned / total * 100, 2) if total else 0,
        "total_distance_m": stats.get("total_distance", 0),
    }
