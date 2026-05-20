import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.api.auth import get_current_user
from app.seed import ensure_debug_users

router = APIRouter()
logger = logging.getLogger(__name__)

IMPORT_DIR = os.environ.get("NEO4J_IMPORT_DIR", "/neo4j_import")

@router.get("/export")
async def export_all(request: Request, user: str = Depends(get_current_user)):
    graph = request.app.state.graph_dao
    try:
        jsonl = await graph.export_apoc()
    except Exception as exc:
        logger.error("APOC export failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"APOC export error: {exc}")
    return Response(
        content=jsonl.encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=neo4j_export.json"},
    )

@router.post("/import")
async def import_all(request: Request, user: str = Depends(get_current_user)):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Тело запроса не может быть пустым")

    os.makedirs(IMPORT_DIR, exist_ok=True)
    filename = f"import_{uuid.uuid4().hex}.json"
    filepath = os.path.join(IMPORT_DIR, filename)

    try:
        with open(filepath, "wb") as f:
            f.write(body)
        logger.info("Wrote import file: %s (%d bytes)", filepath, len(body))

        graph = request.app.state.graph_dao
        result = await graph.import_apoc(filename)
        logger.info("APOC import completed: %s", result)
        await ensure_debug_users(graph)
        return {"status": "ok", "imported": result}
    except Exception as exc:
        logger.error("APOC import failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"APOC import error: {exc}")
    finally:
        try:
            os.remove(filepath)
        except OSError:
            pass
