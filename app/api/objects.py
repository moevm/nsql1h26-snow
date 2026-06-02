import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional

from app.api.auth import get_current_user
from app.api.rate_limit import limiter
from app.seed_data import get_seed_map_objects

router = APIRouter()
logger = logging.getLogger(__name__)

STATIC_OBJECTS = get_seed_map_objects()

def _coerce_datetime(value):
    if value is None or value == "datetime()":
        return None
    native = getattr(value, "to_native", None)
    if callable(native):
        return native()
    return value

def _flatten(row: dict) -> dict:
    name = row.get("object_name") or row.get("name")
    obj_type = row.get("object_type") or row.get("type")
    is_infra = row.get("is_infrastructure")
    if is_infra is None:
        is_infra = obj_type is not None
    elif isinstance(is_infra, str):
        is_infra = is_infra == "True"
    return {
        "id": row.get("id"),
        "name": name,
        "type": obj_type,
        "lat": row.get("lat"),
        "lng": row.get("lng"),
        "location": {"lat": row.get("lat"), "lng": row.get("lng")},
        "capacity": row.get("capacity"),
        "description": row.get("description"),
        "is_infrastructure": is_infra,
        "created_at": _coerce_datetime(row.get("created_at")),
        "updated_at": _coerce_datetime(row.get("updated_at")),
    }

async def _seed_if_needed(graph) -> None:
    existing = await graph.get_map_objects()
    if existing:
        return
    logger.info("Seeding %d static map objects...", len(STATIC_OBJECTS))
    for obj_def in STATIC_OBJECTS:
        obj = dict(obj_def)
        obj["id"] = obj.get("id") or str(uuid.uuid4())
        await graph.create_map_object(obj)
    logger.info("Static map objects seeded")

@router.get("/")
@limiter.limit("60/minute")
async def list_objects(
    request: Request,
    type: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    lat_min: Optional[float] = None,
    lat_max: Optional[float] = None,
    lng_min: Optional[float] = None,
    lng_max: Optional[float] = None,
    only_infrastructure: bool = True,
    created_at_from: Optional[str] = None,
    created_at_to: Optional[str] = None,
    updated_at_from: Optional[str] = None,
    updated_at_to: Optional[str] = None,
    capacity_min: Optional[float] = None,
    capacity_max: Optional[float] = None,
    point_id_filter: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    user: str = Depends(get_current_user),
):
    graph = request.app.state.graph_dao
    result = await graph.get_all_points_paged(
        page=page, page_size=page_size,
        object_name=name, object_type=type, description=description,
        lat_min=lat_min, lat_max=lat_max, lng_min=lng_min, lng_max=lng_max,
        only_infrastructure=only_infrastructure,
        created_at_from=created_at_from, created_at_to=created_at_to,
        updated_at_from=updated_at_from, updated_at_to=updated_at_to,
        capacity_min=capacity_min, capacity_max=capacity_max,
        point_id_filter=point_id_filter,
        sort_by=sort_by, sort_order=sort_order,
    )
    result["items"] = [_flatten(r) for r in result["items"]]
    return result

@router.post("/", status_code=201)
@limiter.limit("30/minute")
async def create_object(
    request: Request,
    body: dict,
    user: str = Depends(get_current_user),
):
    graph = request.app.state.graph_dao
    name = body.get("name", "").strip() if body.get("name") else None
    obj_type = body.get("type", "").strip() if body.get("type") else None
    obj_id = str(uuid.uuid4())
    obj = dict(
        id=obj_id,
        name=name,
        type=obj_type,
        lat=float(body.get("lat", 0)),
        lng=float(body.get("lng", 0)),
        capacity=body.get("capacity"),
        description=body.get("description"),
    )
    await graph.create_map_object(obj)
    logger.info("Created map object %s (%s)", obj_id, obj_type)
    return _flatten({**obj, "created_at": None})

@router.get("/{obj_id}")
async def get_object(request: Request, obj_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    row = await graph.get_map_object(obj_id)
    if not row:
        raise HTTPException(status_code=404, detail="Object not found")
    return _flatten(row)

@router.patch("/{obj_id}")
async def update_object(
    request: Request,
    obj_id: str,
    body: dict,
    user: str = Depends(get_current_user),
):
    graph = request.app.state.graph_dao
    ALLOWED = {"name", "type", "lat", "lng", "capacity", "description"}
    updates = {}
    for k, v in body.items():
        if k not in ALLOWED:
            continue
        if k == "type":
            updates[k] = v or None
        elif v is not None:
            updates[k] = v
    if not updates and "type" not in body:
        raise HTTPException(status_code=400, detail="Nothing to update")
    await graph.update_map_object(obj_id, updates)
    return {"status": "updated", "id": obj_id}

@router.delete("/{obj_id}", status_code=204)
async def delete_object(request: Request, obj_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    await graph.delete_map_object(obj_id)
