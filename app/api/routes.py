import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import get_current_user
from app.api.rate_limit import limiter
from app.models.schemas import CleaningTask, LatLng, RouteRequest, RouteResponse, RouteSegment

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/shortest", response_model=RouteResponse)
@limiter.limit("30/minute")
async def shortest_route(request: Request, body: RouteRequest, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao

    start_node = await graph.find_nearest_node(body.start.lat, body.start.lng)
    end_node = await graph.find_nearest_node(body.end.lat, body.end.lng)

    if not start_node or not end_node:
        raise HTTPException(status_code=404, detail="Cannot find nodes near given coordinates")

    result = await graph.find_shortest_path(start_node["id"], end_node["id"])
    if not result:
        raise HTTPException(status_code=404, detail="No route found")

    nodes = result["nodes"]
    coords = [LatLng(lat=n["lat"], lng=n["lng"]) for n in nodes]

    return RouteResponse(
        segments=[RouteSegment(
            coords=coords,
            distance_m=result["distance"],
            duration_s=result["distance"] / 8.33,
        )],
        total_distance_m=result["distance"],
        total_duration_s=result["distance"] / 8.33,
    )

@router.get("/nearest")
@limiter.limit("60/minute")
async def nearest_node(request: Request, lat: float, lng: float, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    node = await graph.find_nearest_node(lat, lng)
    if not node:
        raise HTTPException(status_code=404, detail="No nodes found")
    return node

@router.post("/preview")
@limiter.limit("30/minute")
async def preview_route(request: Request, body: CleaningTask, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao

    start_node = await graph.find_nearest_node(body.start.lat, body.start.lng)
    end_node = await graph.find_nearest_node(body.end.lat, body.end.lng)

    if not start_node or not end_node:
        raise HTTPException(status_code=404, detail="Cannot find nodes near given coordinates")

    result = await graph.find_shortest_path(start_node["id"], end_node["id"])
    if not result:
        raise HTTPException(status_code=404, detail="No route found between these points")

    nodes = result["nodes"]
    coords = [{"lat": n["lat"], "lng": n["lng"]} for n in nodes]

    return {
        "coords": coords,
        "distance_m": result["distance"],
        "road_count": len(nodes) - 1,
        "start_node": start_node["id"],
        "end_node": end_node["id"],
    }

@router.get("/graph")
@limiter.limit("15/minute")
async def road_graph(request: Request, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    return await graph.get_road_graph()
