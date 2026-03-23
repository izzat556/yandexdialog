import os
import time
import secrets
import urllib.parse
import logging
from flask import Flask, request, jsonify, Response, redirect

app = Flask(__name__)

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)

# ---------- OAuth Settings ----------
CLIENT_ID = os.environ.get("CLIENT_ID", "my_alice_app_001")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "change_me_secret")
TEST_USERNAME = os.environ.get("TEST_USERNAME", "admin")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "123456")

# Redirect URI (Yandex or Cloud Run endpoint)
YANDEX_REDIRECT_URI = os.environ.get(
    "YANDEX_REDIRECT_URI",
    "https://izzat-415138950912.europe-west1.run.app/oauth/authorize"
)

# ---------- Token stores ----------
AUTH_CODES = {}
ACCESS_TOKENS = {}
REFRESH_TOKENS = {}

CODE_TTL_SECONDS = 300
ACCESS_TTL_SECONDS = 3600
REFRESH_TTL_SECONDS = 2592000

# ---------- Test devices ----------
# We store device state separately to support dynamic updates
DEVICES = {
    "lamp_1": {
        "id": "lamp_1",
        "name": "Лампа",
        "description": "Умная лампа",
        "room": "Гостиная",
        "type": "devices.types.light",
        "state": False,          # current on/off state
        "capabilities": [
            {
                "type": "devices.capabilities.on_off",
                "retrievable": True,
                "parameters": {}   # no extra params for on_off
            }
        ],
        "device_info": {
            "manufacturer": "MyCompany",
            "model": "Smart Lamp",
            "hw_version": "1.0",
            "sw_version": "1.0"
        }
    }
}

# ---------- Helper functions ----------
def cleanup_expired():
    now = int(time.time())
    for store in (AUTH_CODES, ACCESS_TOKENS, REFRESH_TOKENS):
        expired = [k for k, v in store.items() if v.get("expires_at", 0) < now]
        for k in expired:
            del store[k]

def validate_client(client_id, client_secret=None):
    if client_id != CLIENT_ID:
        return False
    if client_secret is not None and client_secret != CLIENT_SECRET:
        return False
    return True

def oauth_error(error, description, status=400):
    logging.warning(f"OAuth error: {error} - {description}")
    return jsonify({"error": error, "error_description": description}), status

def login_page(client_id="", redirect_uri="", state="", scope="basic"):
    return f"""
    <!doctype html>
    <html lang="ru">
    <head><meta charset="utf-8"><title>Вход</title></head>
    <body>
      <h2>Вход в аккаунт</h2>
      <form method="post" action="/oauth/authorize">
        <input type="hidden" name="client_id" value="{client_id}">
        <input type="hidden" name="redirect_uri" value="{redirect_uri}">
        <input type="hidden" name="state" value="{state}">
        <input type="hidden" name="scope" value="{scope}">
        <input type="text" name="username" placeholder="Логин" required>
        <input type="password" name="password" placeholder="Пароль" required>
        <button type="submit">Войти и привязать</button>
      </form>
    </body>
    </html>
    """

def get_user_by_token():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.replace("Bearer ", "", 1).strip()
    token_data = ACCESS_TOKENS.get(token)
    if not token_data or token_data["expires_at"] < int(time.time()):
        return None
    return token_data["username"]

# ---------- Routes ----------

@app.route("/", methods=["GET", "HEAD"])
def root():
    if request.method == "HEAD":
        return Response(status=200)
    return jsonify({"status": "ok", "message": "OAuth server is running"})

# Yandex Smart Home main endpoint
@app.route("/v1.0", methods=["POST", "HEAD"])
def yandex_smart_home():
    if request.method == "HEAD":
        return Response(status=200)

    # 1. Parse request body
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Invalid JSON"}), 400

    # 2. Extract authorization token from the JSON body
    auth = body.get("headers", {}).get("authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401

    token = auth.replace("Bearer ", "", 1).strip()

    # 3. Validate token
    token_data = ACCESS_TOKENS.get(token)
    if not token_data or token_data["expires_at"] < int(time.time()):
        return jsonify({"error": "Unauthorized"}), 401

    user_id = token_data["username"]   # This becomes the user_id

    # 4. Get request metadata
    request_type = body.get("request_type")
    api_version = body.get("api_version", 1.0)
    request_id = body.get("headers", {}).get("request_id", "")

    logging.info(f"Smart Home request: type={request_type}, user={user_id}, req_id={request_id}")

    # 5. Handle different request types
    if request_type == "discovery":
        devices_list = []
        for dev_id, dev in DEVICES.items():
            devices_list.append({
                "id": dev["id"],
                "name": dev["name"],
                "description": dev.get("description", ""),
                "room": dev.get("room", ""),
                "type": dev["type"],
                "capabilities": dev["capabilities"],
                "device_info": dev["device_info"]
            })

        return jsonify({
            "request_id": request_id,
            "payload": {
                "user_id": user_id,
                "devices": devices_list
            }
        })

    elif request_type == "state":
        devices_state = []
        for dev_id, dev in DEVICES.items():
            capabilities_state = []
            for cap in dev["capabilities"]:
                if cap["type"] == "devices.capabilities.on_off":
                    capabilities_state.append({
                        "type": "devices.capabilities.on_off",
                        "state": {
                            "instance": "on",
                            "value": dev["state"]
                        }
                    })
            devices_state.append({
                "id": dev["id"],
                "capabilities": capabilities_state
            })

        return jsonify({
            "request_id": request_id,
            "payload": {
                "devices": devices_state
            }
        })

    elif request_type == "action":
        payload = body.get("payload", {})
        devices_actions = payload.get("devices", [])
        updated_devices = []

        for action in devices_actions:
            device_id = action.get("id")
            if device_id not in DEVICES:
                continue

            capabilities = action.get("capabilities", [])
            device_state_updated = False

            for cap in capabilities:
                cap_type = cap.get("type")
                if cap_type == "devices.capabilities.on_off":
                    new_state = cap.get("state", {}).get("value")
                    if new_state is not None:
                        DEVICES[device_id]["state"] = new_state
                        device_state_updated = True

            updated_capabilities = []
            if device_state_updated:
                updated_capabilities.append({
                    "type": "devices.capabilities.on_off",
                    "state": {
                        "instance": "on",
                        "action_result": {
                            "status": "DONE"
                        }
                    }
                })
            updated_devices.append({
                "id": device_id,
                "capabilities": updated_capabilities
            })

        return jsonify({
            "request_id": request_id,
            "payload": {
                "devices": updated_devices
            }
        })

    else:
        return jsonify({"error": "Unsupported request_type"}), 400
          

# Keep legacy endpoints (optional, not used by Yandex Smart Home)
@app.route("/v1.0/user/unlink", methods=["POST", "HEAD"])
def user_unlink():
    if request.method == "HEAD":
        return "", 200
    return jsonify({"status": "ok"})

@app.route("/v1.0/user/devices", methods=["GET", "HEAD"])
def user_devices():
    if request.method == "HEAD":
        return "", 200
    # This endpoint is not used by Yandex Smart Home, but we keep it for compatibility
    return jsonify({
        "user_id": "user_001",
        "devices": list(DEVICES.values())
    })

# ---------- OAuth endpoints ----------
@app.route("/oauth/authorize", methods=["GET", "POST", "HEAD"])
def authorize():
    cleanup_expired()
    if request.method == "HEAD":
        return Response(status=200)

    if request.method == "GET":
        client_id = request.args.get("client_id", "")
        redirect_uri = request.args.get("redirect_uri", "")
        response_type = request.args.get("response_type", "")
        state = request.args.get("state", "")
        scope = request.args.get("scope", "basic")

        if not client_id or not redirect_uri or response_type != "code":
            return Response("Invalid OAuth request", status=400)
        if not validate_client(client_id):
            return Response("Invalid client_id", status=401)
        if redirect_uri != YANDEX_REDIRECT_URI and not redirect_uri.startswith("https://"):
            return Response("Invalid redirect_uri", status=400)

        return Response(login_page(client_id, redirect_uri, state, scope), mimetype="text/html")

    # POST login
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    client_id = request.form.get("client_id", "")
    redirect_uri = request.form.get("redirect_uri", "")
    state = request.form.get("state", "")
    scope = request.form.get("scope", "basic")

    if not validate_client(client_id):
        return Response("Invalid client_id", status=401)
    if redirect_uri != YANDEX_REDIRECT_URI and not redirect_uri.startswith("https://"):
        return Response("Invalid redirect_uri", status=400)
    if username != TEST_USERNAME or password != TEST_PASSWORD:
        return Response("Неверный логин или пароль", status=401)

    code = secrets.token_urlsafe(32)
    AUTH_CODES[code] = {
        "username": username,
        "client_id": client_id,
        "scope": scope,
        "expires_at": int(time.time()) + CODE_TTL_SECONDS,
        "used": False
    }
    query = urllib.parse.urlencode({"code": code, "state": state})
    return redirect(f"{redirect_uri}?{query}", code=302)

@app.route("/oauth/token", methods=["POST", "HEAD"])
def token():
    cleanup_expired()
    if request.method == "HEAD":
        return Response(status=200)
    grant_type = request.form.get("grant_type", "")
    code = request.form.get("code", "")
    client_id = request.form.get("client_id", "")
    client_secret = request.form.get("client_secret", "")

    if grant_type != "authorization_code":
        return oauth_error("unsupported_grant_type", "Only authorization_code is supported")
    if not validate_client(client_id, client_secret):
        return oauth_error("invalid_client", "Invalid client credentials", 401)
    if code not in AUTH_CODES:
        return oauth_error("invalid_grant", "Invalid authorization code")

    code_data = AUTH_CODES[code]
    if code_data["used"]:
        return oauth_error("invalid_grant", "Code already used")
    if code_data["expires_at"] < int(time.time()):
        return oauth_error("invalid_grant", "Code expired")

    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(32)
    ACCESS_TOKENS[access_token] = {"username": code_data["username"], "expires_at": int(time.time()) + ACCESS_TTL_SECONDS}
    REFRESH_TOKENS[refresh_token] = {"username": code_data["username"], "expires_at": int(time.time()) + REFRESH_TTL_SECONDS}
    code_data["used"] = True

    return jsonify({
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TTL_SECONDS,
        "refresh_token": refresh_token,
        "scope": code_data["scope"]
    })

@app.route("/oauth/refresh", methods=["POST", "HEAD"])
def refresh():
    cleanup_expired()
    if request.method == "HEAD":
        return Response(status=200)
    grant_type = request.form.get("grant_type", "")
    refresh_token = request.form.get("refresh_token", "")
    client_id = request.form.get("client_id", "")
    client_secret = request.form.get("client_secret", "")

    if grant_type and grant_type != "refresh_token":
        return oauth_error("unsupported_grant_type", "Only refresh_token is supported")
    if not validate_client(client_id, client_secret):
        return oauth_error("invalid_client", "Invalid client credentials", 401)
    if refresh_token not in REFRESH_TOKENS:
        return oauth_error("invalid_grant", "Invalid refresh token")

    token_data = REFRESH_TOKENS[refresh_token]
    if token_data["expires_at"] < int(time.time()):
        return oauth_error("invalid_grant", "Refresh token expired")

    new_access_token = secrets.token_urlsafe(32)
    ACCESS_TOKENS[new_access_token] = {"username": token_data["username"], "expires_at": int(time.time()) + ACCESS_TTL_SECONDS}

    return jsonify({
        "access_token": new_access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TTL_SECONDS,
        "refresh_token": refresh_token,
        "scope": "basic"
    })

# ---------- Run ----------
