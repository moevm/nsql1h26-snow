import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from passlib.context import CryptContext

from app.api.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.get("/")
async def list_users(request: Request, name: str | None = None, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    return await graph.get_users(name=name)

@router.post("/", status_code=201)
async def create_user(request: Request, body: dict, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    name = body.get("name", "").strip()
    password = body.get("password", "").strip()
    if not name or not password:
        raise HTTPException(status_code=400, detail="name and password required")
    existing = await graph.get_user_by_name(name)
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")
    user_id = str(uuid.uuid4())
    await graph.create_user({
        "id": user_id,
        "name": name,
        "password_hash": pwd_context.hash(password),
        "role": body.get("role", "operator"),
    })
    return {"id": user_id, "name": name, "role": body.get("role", "operator")}

@router.get("/{user_id}")
async def get_user(request: Request, user_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    row = await graph.get_user(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row

@router.patch("/{user_id}")
async def update_user(request: Request, user_id: str, body: dict, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    updates = {}
    if "name" in body:
        updates["name"] = body["name"]
    if "role" in body:
        updates["role"] = body["role"]
    if "password" in body and body["password"]:
        updates["password_hash"] = pwd_context.hash(body["password"])
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    await graph.update_user(user_id, updates)
    return {"status": "updated", "id": user_id}

@router.delete("/{user_id}", status_code=204)
async def delete_user(request: Request, user_id: str, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    await graph.delete_user(user_id)
