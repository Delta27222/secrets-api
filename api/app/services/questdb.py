import requests
from typing import Dict, Any
from ..core.config import EC2_INSTANCE_URL

class QuestDBService:
    """Servicio para interactuar con QuestDB usando API HTTP"""
    def __init__(self, base_url: str = EC2_INSTANCE_URL):
        self.base_url = base_url
        self.exec_url = f"{base_url}/exec"
    def execute_query(self, query: str) -> Dict[str, Any]:
        """Ejecutar una consulta SQL en QuestDB"""
        try:
            response = requests.get(self.exec_url, params={'query': query}, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Error en consulta QuestDB: {e}")
            return {"error": str(e), "dataset": [], "count": 0}

# Instancia global del servicio
questdb_service = QuestDBService()
