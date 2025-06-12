import json
import os
import urllib
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, Optional

import keyring
import requests
from dotenv.main import load_dotenv
from starlette.datastructures import Secret

from .config import CLIENT_ID, DEV_API_URL, PROD_API_URL, REDIRECT_URI

# Global variable to store the OAuth authorization code
auth_code = None

CONFIG_DIR = Path.home() / ".config" / "tek-secrets"
TOKEN_FILE = CONFIG_DIR / "github_token.json"
SERVICE_NAME = "tek_secrets_github"


def ensure_config_dir() -> None:
    """Ensure the configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.touch(exist_ok=True)


def store_token(token_data: Dict) -> None:
    """
    Store token securely using system keychain with file fallback.

    Args:
        token_data: Dictionary containing token information including:
            - access_token
            - token_type
            - expires_in (optional)
            - refresh_token (optional)
            - scope
    """
    ensure_config_dir()

    # Store sensitive data in system keychain
    try:
        keyring.set_password(SERVICE_NAME, "access_token",
                             token_data["access_token"])
        if "refresh_token" in token_data:
            keyring.set_password(
                SERVICE_NAME, "refresh_token", token_data["refresh_token"])
    except Exception:
        # Fallback to file storage if keyring fails
        token_data["stored_at"] = datetime.utcnow().isoformat()
        with open(TOKEN_FILE, "w") as f:
            json.dump(token_data, f)
        TOKEN_FILE.chmod(0o600)  # Restrict file permissions


def load_token() -> Optional[Dict]:
    """
    Load stored token, checking validity.

    Returns:
        Dictionary with token data if valid token exists, None otherwise
    """
    try:
        # Try to get from keychain first
        access_token = keyring.get_password(SERVICE_NAME, "access_token")
        refresh_token = keyring.get_password(SERVICE_NAME, "refresh_token")

        if access_token:
            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "source": "keyring"
            }
    except Exception:
        pass

    # Fallback to file storage
    if TOKEN_FILE.exists():
        try:
            with open(TOKEN_FILE, "r") as f:
                token_data = json.load(f)

            token_data["source"] = "file"
            return token_data
        except Exception:
            return None

    return None


def get_valid_token() -> Optional[str]:
    """
    Get a valid access token, refreshing if necessary.

    Returns:
        Valid access token or None if no valid token available
    """
    token_data = load_token()
    if not token_data:
        return None

    # Here you could add token refresh logic if your API supports it
    # if token_needs_refresh(token_data):
    #     return refresh_access_token(token_data["refresh_token"])

    return token_data["access_token"]


def is_authorized() -> bool:
    token = get_valid_token()
    return token != None


def clear_stored_token() -> None:
    """Remove all stored token information."""
    try:
        keyring.delete_password(SERVICE_NAME, "access_token")
        keyring.delete_password(SERVICE_NAME, "refresh_token")
    except Exception:
        pass

    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP server handler to capture GitHub OAuth callback with authorization code."""

    def do_GET(self):
        """Handle GET request from GitHub OAuth redirect."""
        global auth_code

        if self.path.startswith('/'):
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)

            if 'code' in params:
                # Success case: store the authorization code
                auth_code = params['code'][0]

                # Send success response to user's browser
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(
                    b"<h1>Authentication successful!</h1><p>You can close this window.</p>")
            else:
                # Error case: no code parameter in callback
                self.send_response(400)
                self.end_headers()
                self.wfile.write(
                    b"Error: Authorization code not received")
        else:
            # Handle other paths (shouldn't happen in normal flow)
            self.send_response(404)
            self.end_headers()


def run_server():
    """Start a temporary HTTP server to listen for OAuth callback.

    The server runs on localhost:8080 and handles exactly one request.
    """
    server = HTTPServer(('localhost', 8080), CallbackHandler)
    server.handle_request()  # This will block until a request is received


def get_github_auth_code() -> str:
    """Initiate GitHub OAuth flow and return the authorization code.

    Steps:
    1. Opens user's browser to GitHub authorization page
    2. Starts a local server to catch the redirect with auth code
    3. Returns the obtained authorization code

    Returns:
        str: The authorization code from GitHub

    Raises:
        RuntimeError: If authentication fails or no code is received
    """
    global auth_code
    auth_code = None  # Reset any previous code

    # Build authorization URL with required parameters
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': 'user user:email',  # Adjust scopes as needed
        'response_type': 'code',
    }
    auth_url = f"https://github.com/login/oauth/authorize?{urllib.parse.urlencode(params)}"

    # Open browser for user authentication
    webbrowser.open(auth_url)
    print("Opened GitHub authorization in your browser...", auth_url)

    # Start server to catch the callback
    print("Waiting for GitHub callback on localhost:8080...")
    run_server()

    if not auth_code:
        raise RuntimeError("Failed to obtain authorization code")

    return auth_code


def exchange_code_for_token(auth_code: str, dev: Optional[bool] = False) -> Optional[str]:
    """
    Exchanges GitHub authorization code for an access token by calling local API endpoint.

    Args:
        auth_code: The authorization code received from GitHub OAuth flow

    Returns:
        The access token if successful, None otherwise

    Raises:
        requests.exceptions.RequestException: If the request fails
    """
    if dev:
        API_URL = DEV_API_URL
    else:
        API_URL = PROD_API_URL
    url = f"{API_URL}/v1/auth/github/token"
    headers = {
        "accept": "application/json"
    }
    params = {
        "code": auth_code
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raises exception for 4XX/5XX responses

        token_data = response.json()
        store_token(token_data)

        return token_data.get("access_token")

    except requests.exceptions.RequestException as e:
        print(f"Error exchanging code for token: {e}")
        return None
    except ValueError as e:
        print(f"Error parsing JSON response: {e}")
        return None


def github_login_flow() -> Optional[str]:
    """Complete GitHub OAuth login flow returning access token."""
    try:
        # Step 1: Get authorization code
        auth_code = get_github_auth_code()
        if not auth_code:
            print("Failed to get authorization code")
            return None

        # Step 2: Exchange code for access token
        access_token = exchange_code_for_token(auth_code)
        return access_token

    except Exception as e:
        print(f"Login failed: {e}")
        return None


def get_github_token_or_start_flow() -> str:
    authorized = is_authorized()
    if authorized:
        github_token = get_valid_token()
    else:
        auth_code = get_github_auth_code()
        github_token = exchange_code_for_token(auth_code)
    return github_token
