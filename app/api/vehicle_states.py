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
    created_at_from: str | None = None,
    created_at_to: str | None = None,
    updated_at_from: str | None = None,
    updated_at_to: str | None = None,
    lat_min: float | None = None,
    lat_max: float | None = None,
    lng_min: float | None = None,
    lng_max: float | None = None,
    fuel_min: float | None = None,
    fuel_max: float | None = None,
    snow_min: float | None = None,
    snow_max: float | None = None,
    dist_min: float | None = None,
    dist_max: float | None = None,
    speed_min: float | None = None,
    speed_max: float | None = None,
    travel_speed_min: float | None = None,
    travel_speed_max: float | None = None,
    cleaning_speed_min: float | None = None,
    cleaning_speed_max: float | None = None,
    fuel_cap_min: float | None = None,
    fuel_cap_max: float | None = None,
    snow_cap_min: float | None = None,
    snow_cap_max: float | None = None,
    breakdown_min: float | None = None,
    breakdown_max: float | None = None,
    repair_rem_min: float | None = None,
    repair_rem_max: float | None = None,
    progress_min: float | None = None,
    progress_max: float | None = None,
    tick_min: int | None = None,
    tick_max: int | None = None,
    target_type_filter: str | None = None,
    target_id_filter: str | None = None,
    source_id_filter: str | None = None,
    dest_id_filter: str | None = None,
    step_id_filter: str | None = None,
    machine_id_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user: str = Depends(get_current_user),
):
    graph = request.app.state.graph_dao
    return await graph.get_vehicle_states(
        page=page, page_size=page_size,
        step_id=step_id, sim_id=sim_id,
        status=status, vehicle_type=vehicle_type,
        created_at_from=created_at_from, created_at_to=created_at_to,
        updated_at_from=updated_at_from, updated_at_to=updated_at_to,
        lat_min=lat_min, lat_max=lat_max,
        lng_min=lng_min, lng_max=lng_max,
        fuel_min=fuel_min, fuel_max=fuel_max,
        snow_min=snow_min, snow_max=snow_max,
        dist_min=dist_min, dist_max=dist_max,
        speed_min=speed_min, speed_max=speed_max,
        travel_speed_min=travel_speed_min, travel_speed_max=travel_speed_max,
        cleaning_speed_min=cleaning_speed_min, cleaning_speed_max=cleaning_speed_max,
        fuel_cap_min=fuel_cap_min, fuel_cap_max=fuel_cap_max,
        snow_cap_min=snow_cap_min, snow_cap_max=snow_cap_max,
        breakdown_min=breakdown_min, breakdown_max=breakdown_max,
        repair_rem_min=repair_rem_min, repair_rem_max=repair_rem_max,
        progress_min=progress_min, progress_max=progress_max,
        tick_min=tick_min, tick_max=tick_max,
        target_type_filter=target_type_filter, target_id_filter=target_id_filter,
        source_id_filter=source_id_filter, dest_id_filter=dest_id_filter,
        step_id_filter=step_id_filter, machine_id_filter=machine_id_filter,
    )

@router.get("/{vs_id}")
async def get_vehicle_state(request: Request, vs_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    row = await graph.get_vehicle_state(vs_id)
    if not row:
        raise HTTPException(status_code=404, detail="VehicleState not found")
    return row

@router.get("/{vs_id}/history")
async def get_vehicle_history(
    request: Request, vs_id: str,
    page: int = 1, page_size: int = 20,
    user: str = Depends(get_current_user),
):
    graph = request.app.state.graph_dao
    return await graph.get_vehicle_history(vs_id, page=page, page_size=page_size)

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
