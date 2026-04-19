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
    data = [LogResponse(**row) for row in page_rows]
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
) -> PaginatedLogsResponse:
    """Wrapper async que ejecuta queries en thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _execute_log_query,
        target_id,
        target_ids,
        target_type,
        user_id,
        page,
        per_page,
    )


async def get_all_logs(page: int = 1, per_page: int = 20) -> PaginatedLogsResponse:
    """Wrapper async que ejecuta queries en thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _execute_log_query,
        None,  # target_id
        None,  # target_ids
        None,  # target_type
        None,  # user_id
        page,
        per_page,
    )