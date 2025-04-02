from typing import Dict, Optional

import requests

from ..core.config import GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET


async def get_github_token(auth_code: str) -> Optional[Dict[str, str]]:
    """
    Versión mejorada con mejor manejo de errores.

    Args:
        auth_code (str): Código de autorización

    Returns:
        dict: Datos del token si es exitoso, None si falla
    """
    try:
        # Configuración (mejor usar variables de entorno)
        config = {
            "client_id": str(GITHUB_CLIENT_ID),
            "client_secret": str(GITHUB_CLIENT_SECRET),
        }

        response = requests.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": auth_code,
            },
            headers={"Accept": "application/json"},
            timeout=10  # Timeout de 10 segundos
        )

        response.raise_for_status()
        data = response.json()

        if "error" in data:
            print(
                f"GitHub Error: {data.get('error_description', 'Error desconocido')}")
            return None

        return data

    except requests.exceptions.RequestException as e:
        print(f"Error en la solicitud: {str(e)}")
        return None
