from typing import List, Optional

from fastapi import APIRouter, Query

from ....services.logs import get_logs_by_filters
from ....models.logs import LogResponse, PaginatedLogsResponse


router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/", response_model=PaginatedLogsResponse, summary="List logs", description="List logs by filters or all logs by pagination", tags=["logs"])
async def list_logs(
    target_id: Optional[str] = Query(None),
    target_ids: Optional[List[str]] = Query(None),
    target_type: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    level: Optional[str] = Query(None, description="INFO o ERROR. Sin valor, devuelve ambos."),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    # get_logs_by_filters ya cubre el caso sin filtros, así que no hace falta
    # ramificar: si todos los parámetros son None, la query sale sin WHERE.
    return await get_logs_by_filters(
        target_id, target_ids, target_type, user_id, page, per_page, level
    )


