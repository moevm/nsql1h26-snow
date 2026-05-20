import logging
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.config import get_settings
from app.models.schemas import TokenRequest, TokenResponse

router = APIRouter()
settings = get_settings()
logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError as exc:
        logger.error("JWT decode failed: %s", exc)
        raise credentials_exception
    return username

async def _verify_user(username: str, password: str, graph) -> bool:
    rows = await graph.run_query(
        "MATCH (u:User {name: $name}) RETURN u.password_hash AS password_hash",
        name=username,
    )
    if not rows or not rows[0].get("password_hash"):
        return False
    stored_hash = rows[0]["password_hash"]
    if isinstance(stored_hash, str):
        stored_hash = stored_hash.encode()
    return bcrypt.checkpw(password.encode(), stored_hash)

@router.post("/token", response_model=TokenResponse)
async def login(request: Request, body: TokenRequest):
    graph = request.app.state.graph_dao
    if not await _verify_user(body.username, body.password, graph):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token({"sub": body.username})
    return TokenResponse(access_token=token)

@router.get("/me")
async def me(user: str = Depends(get_current_user)):
    return {"username": user}
