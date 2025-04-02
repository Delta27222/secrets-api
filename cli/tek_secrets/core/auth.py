import os
import urllib
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

import requests
from dotenv.main import load_dotenv
from starlette.datastructures import Secret

from .._secrets import get_secret
from .config import API_URL, CLIENT_ID, REDIRECT_URI

# Global variable to store the OAuth authorization code
auth_code = None


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP server handler to capture GitHub OAuth callback with authorization code."""

    def do_GET(self):
        """Handle GET request from GitHub OAuth redirect."""
        global auth_code

        # Check if this is our OAuth callback
        print(self.path)
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
    print("Opened GitHub authorization in your browser...")

    # Start server to catch the callback
    print("Waiting for GitHub callback on localhost:8080...")
    run_server()

    if not auth_code:
        raise RuntimeError("Failed to obtain authorization code")

    return auth_code


def exchange_code_for_token(auth_code: str) -> Optional[str]:
    """
    Exchanges GitHub authorization code for an access token by calling local API endpoint.

    Args:
        auth_code: The authorization code received from GitHub OAuth flow

    Returns:
        The access token if successful, None otherwise

    Raises:
        requests.exceptions.RequestException: If the request fails
    """
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
        return token_data.get("access_token")

    except requests.exceptions.RequestException as e:
        print(f"Error exchanging code for token: {e}")
        return None
    except ValueError as e:
        print(f"Error parsing JSON response: {e}")
        return None
