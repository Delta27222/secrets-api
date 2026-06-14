"""Helpers para queries MongoDB con IDs str u ObjectId."""

from bson import ObjectId


def id_query_value(value: str | ObjectId | None):
    """
    Valor de filtro para campos que pueden ser str u ObjectId en la BD.

    Uso: collection.find({"project_id": id_query_value(project_id)})
    """
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return {"$in": [str(value), value]}
    s = str(value)
    if ObjectId.is_valid(s):
        return {"$in": [s, ObjectId(s)]}
    return s
