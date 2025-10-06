from typing import List, Dict, Any, Optional

from ..services.questdb import QuestDBService, questdb_service

class QuestDBQuery:
    """Query builder minimalista para QuestDB (estilo ORM)."""

    def __init__(self, service: QuestDBService, table_name: str):
        self.service = service
        self.table_name = table_name
        self.where_conditions: List[str] = []
        self.order_by_clause: Optional[str] = None
        self.limit_value: Optional[int] = None
        self.offset_value: Optional[int] = None
        self.select_fields: List[str] = ["*"]

    def select(self, *fields: str) -> "QuestDBQuery":
        self.select_fields = list(fields) if fields else ["*"]
        return self

    def where(self, **kwargs) -> "QuestDBQuery":
        for field, value in kwargs.items():
            if isinstance(value, list):
                values_str = "', '".join(str(v) for v in value)
                self.where_conditions.append(f"{field} IN ('{values_str}')")
            else:
                self.where_conditions.append(f"{field} = '{value}'")
        return self

    def where_like(self, field: str, pattern: str) -> "QuestDBQuery":
        self.where_conditions.append(f"{field} LIKE '{pattern}'")
        return self

    def where_between(self, field: str, start: str, end: str) -> "QuestDBQuery":
        self.where_conditions.append(f"{field} BETWEEN '{start}' AND '{end}'")
        return self

    def order_by(self, field: str, desc: bool = True) -> "QuestDBQuery":
        self.order_by_clause = f"ORDER BY {field} {'DESC' if desc else 'ASC'}"
        return self

    def limit(self, count: int) -> "QuestDBQuery":
        self.limit_value = count
        return self

    def offset(self, skip: int) -> "QuestDBQuery":
        self.offset_value = skip
        return self

    def _build_query(self) -> str:
        query = f"SELECT {', '.join(self.select_fields)} FROM {self.table_name}"
        if self.where_conditions:
            query += " WHERE " + " AND ".join(self.where_conditions)
        if self.order_by_clause:
            query += " " + self.order_by_clause
        if self.limit_value is not None:
            query += f" LIMIT {self.limit_value}"
            if self.offset_value is not None and self.offset_value > 0:
                query += f" OFFSET {self.offset_value}"
        elif self.offset_value is not None and self.offset_value > 0:
            # Permit OFFSET without LIMIT
            query += f" OFFSET {self.offset_value}"
        return query

    def count(self) -> int:
        """Devuelve el total de filas que cumplen las condiciones actuales (sin ORDER/LIMIT)."""
        query = f"SELECT count() as count FROM {self.table_name}"
        if self.where_conditions:
            query += " WHERE " + " AND ".join(self.where_conditions)
        result = self.service.execute_query(query)
        if result.get("error"):
            return 0
        dataset = result.get("dataset", [])
        if not dataset:
            return 0
        try:
            return int(dataset[0][0])
        except (ValueError, TypeError):
            columns = [col.get("name") for col in result.get("columns", [])]
            if "count" in columns:
                idx = columns.index("count")
                try:
                    return int(dataset[0][idx])
                except Exception:
                    return 0
        return 0

    def all(self) -> List[Dict[str, Any]]:
        result = self.service.execute_query(self._build_query())
        if result.get("error"):
            return []
        columns = [col["name"] for col in result.get("columns", [])]
        dataset = result.get("dataset", [])
        return [dict(zip(columns, row)) for row in dataset]

    def first(self) -> Optional[Dict[str, Any]]:
        self.limit(1)
        rows = self.all()
        return rows[0] if rows else None


class LogQuery(QuestDBQuery):
    """Query builder específico para la tabla Logs."""

    def __init__(self, service: QuestDBService):
        super().__init__(service, "Logs")

    def by_target_id(self, target_id: str) -> "LogQuery":
        return self.where(idTarget=target_id)

    def by_user(self, user_id: str) -> "LogQuery":
        return self.where(user=user_id)

    def by_target_type(self, target_type: str) -> "LogQuery":
        return self.where(targetType=target_type)

    def by_action(self, action: str) -> "LogQuery":
        return self.where(action=action)

    def by_date_range(self, start_iso: str, end_iso: str) -> "LogQuery":
        return self.where_between("date", start_iso, end_iso)

    def recent(self, limit_count: int = 100) -> "LogQuery":
        return self.order_by("date", desc=True).limit(limit_count)

    def by_multiple_targets(self, target_ids: List[str]) -> "LogQuery":
        if not target_ids:
            return self
        values_str = "', '".join(str(v) for v in target_ids)
        self.where_conditions.append(f"idTarget IN ('{values_str}')")
        return self


def get_log_query() -> LogQuery:
    """Factory para obtener una instancia lista de LogQuery."""
    return LogQuery(questdb_service)


