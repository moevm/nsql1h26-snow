import logging
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/")
async def list_steps(
    request: Request,
    sim_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    tick_min: int | None = None,
    tick_max: int | None = None,
    user: str = Depends(get_current_user),
):
    graph = request.app.state.graph_dao

    return await graph.get_simulation_steps(sim_id=sim_id, page=page, page_size=page_size, tick_min=tick_min, tick_max=tick_max)

@router.get("/{step_id}")
async def get_step(request: Request, step_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    row = await graph.get_simulation_step(step_id)
    if not row:
        raise HTTPException(status_code=404, detail="SimulationStep not found")
    return row

@router.get("/{step_id}/vehicles")
async def get_step_vehicles(request: Request, step_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    return await graph.get_step_vehicle_states(step_id)

@router.patch("/{step_id}")
async def update_step(request: Request, step_id: str, body: dict, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    await graph.update_simulation_step(step_id, body)
    row = await graph.get_simulation_step(step_id)
    if not row:
        raise HTTPException(status_code=404, detail="SimulationStep not found")
    return row

@router.delete("/{step_id}", status_code=204)
async def delete_step(request: Request, step_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    await graph.delete_simulation_step(step_id)
