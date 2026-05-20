import logging
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import get_current_user
from app.models.enums import VehicleStatus

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/")
async def list_vehicle_states(
    request: Request,
    step_id: str | None = None,
    sim_id: str | None = None,
    status: str | None = None,
    vehicle_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user: str = Depends(get_current_user),
):
    graph = request.app.state.graph_dao
    return await graph.get_vehicle_states(
        page=page, page_size=page_size,
        step_id=step_id, sim_id=sim_id,
        status=status, vehicle_type=vehicle_type,
    )

@router.get("/{vs_id}")
async def get_vehicle_state(request: Request, vs_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    row = await graph.get_vehicle_state(vs_id)
    if not row:
        raise HTTPException(status_code=404, detail="VehicleState not found")
    return row

@router.get("/{vs_id}/history")
async def get_vehicle_history(request: Request, vs_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    return await graph.get_vehicle_history(vs_id)

@router.patch("/{vs_id}")
async def update_vehicle_state(request: Request, vs_id: str, body: dict, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    existing = await graph.get_vehicle_state(vs_id)
    if not existing:
        raise HTTPException(status_code=404, detail="VehicleState not found")

    await graph.update_vehicle_state(vs_id, body)
    sim_id = existing.get("simulation_id")
    if sim_id:
        try:
            from app.api.simulation import _simulations
            engine = _simulations.get(sim_id)
            if engine:
                vehicle = next((v for v in engine.vehicles if v.id == vs_id), None)
                if vehicle:
                    if "status" in body and body["status"]:
                        vehicle.status = VehicleStatus(body["status"])
                        if vehicle.status == VehicleStatus.BROKEN:
                            vehicle.target_type = None
                            vehicle.target_id = None
                            vehicle.target_location = None
                            vehicle.path_waypoints = []
                    if "fuel_level" in body and body["fuel_level"] is not None:
                        vehicle.fuel_level = float(body["fuel_level"])
                    if "snow_loaded_m3" in body and body["snow_loaded_m3"] is not None:
                        vehicle.snow_loaded_m3 = float(body["snow_loaded_m3"])
                    if "travel_speed_kmh" in body and body["travel_speed_kmh"] is not None:
                        vehicle.travel_speed_kmh = float(body["travel_speed_kmh"])
                    if "cleaning_speed_kmh" in body and body["cleaning_speed_kmh"] is not None:
                        vehicle.cleaning_speed_kmh = float(body["cleaning_speed_kmh"])
                    if "fuel_consumption_l_per_km" in body and body["fuel_consumption_l_per_km"] is not None:
                        vehicle.fuel_consumption_l_per_km = float(body["fuel_consumption_l_per_km"])
                    if "fuel_capacity_l" in body and body["fuel_capacity_l"] is not None:
                        vehicle.fuel_capacity_l = float(body["fuel_capacity_l"])
                        vehicle.fuel_level = min(vehicle.fuel_level, vehicle.fuel_capacity_l)
                    if "snow_capacity_m3" in body and body["snow_capacity_m3"] is not None:
                        vehicle.snow_capacity_m3 = float(body["snow_capacity_m3"])
                        vehicle.snow_loaded_m3 = min(vehicle.snow_loaded_m3, vehicle.snow_capacity_m3)
                    if "breakdown_probability" in body and body["breakdown_probability"] is not None:
                        vehicle.breakdown_probability = float(body["breakdown_probability"])
                    if "repair_time_min" in body and body["repair_time_min"] is not None:
                        vehicle.repair_time_min = float(body["repair_time_min"])
                    if "current_road" in body:
                        vehicle.current_road = body["current_road"]
                    if "repair_remaining_min" in body and body["repair_remaining_min"] is not None:
                        vehicle.repair_remaining_min = float(body["repair_remaining_min"])
                    engine._refresh_state_metrics()
        except Exception:
            logger.exception("Failed to sync live vehicle state for %s", vs_id)

    row = await graph.get_vehicle_state(vs_id)
    if not row:
        raise HTTPException(status_code=404, detail="VehicleState not found")
    return row
