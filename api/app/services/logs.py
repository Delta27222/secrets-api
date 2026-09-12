import asyncio
from typing import List, Optional

from ..core.questdb_orm import get_log_query
from ..models.logs import LogResponse, PaginatedLogsResponse, PaginationMeta


def _execute_log_query(
    target_id: Optional[str] = None,
    target_ids: Optional[List[str]] = None,
    target_type: Optional[str] = None,
    user_id: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
    level: Optional[str] = None,
) -> PaginatedLogsResponse:
    """Ejecución síncrona de queries a QuestDB. Llamar via run_in_executor."""
    query = get_log_query()
    if target_ids:
        query = query.by_multiple_targets(target_ids)
    elif target_id:
        query = query.by_target_id(target_id)
    if target_type:
        query = query.by_target_type(target_type)
    if user_id:
        query = query.by_user(user_id)
    if level:
        query = query.by_level(level)

    total = query.count()
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 20

    total_limit = page * per_page
    rows = query.recent(total_limit).all()
    start = (page - 1) * per_page
    end = start + per_page
    page_rows = rows[start:end]
    # La tabla Logs de QuestDB no tiene columna `id`; el front la usa solo como
    # React key. Se sintetiza una única por fila (date tiene precisión de micros).
    data = []
    for i, row in enumerate(page_rows):
        row = dict(row)
        if not row.get("id"):
            row["id"] = f"{row.get('date', '')}-{row.get('idTarget', '')}-{start + i}"
        data.append(LogResponse(**row))
    total_pages = (total + per_page - 1) // per_page if per_page else 0

    meta = PaginationMeta(
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )
    return PaginatedLogsResponse(data=data, meta=meta)


async def get_logs_by_filters(
    target_id: Optional[str] = None,
    target_ids: Optional[List[str]] = None,
    target_type: Optional[str] = None,
    user_id: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
    level: Optional[str] = None,
) -> PaginatedLogsResponse:
    """Wrapper async que ejecuta queries en thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _execute_log_query,
        target_id,
        target_ids,
        target_type,
        user_id,
        page,
        per_page,
        level,
    )


async def get_all_logs(page: int = 1, per_page: int = 20, level: Optional[str] = None) -> PaginatedLogsResponse:
    """Wrapper async que ejecuta queries en thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _execute_log_query,
        None,  # target_id
        None,  # target_ids
        None,  # target_type
        None,  # user_id
        page,
        per_page,
        level,
    )
