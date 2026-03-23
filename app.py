import os
import time
import secrets
import urllib.parse
from flask import Flask, request, jsonify, Response, redirect

app = Flask(__name__)

# OAuth настройки
CLIENT_ID = os.environ.get("CLIENT_ID", "my_alice_app_001")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "change_me_secret")
TEST_USERNAME = os.environ.get("TEST_USERNAME", "admin")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "123456")
YANDEX_REDIRECT_URI = "https://social.yandex.net/broker/redirect"

AUTH_CODES = {}
ACCESS_TOKENS = {}
REFRESH_TOKENS = {}

CODE_TTL_SECONDS = 300
ACCESS_TTL_SECONDS = 3600
REFRESH_TTL_SECONDS = 2592000

# Простое тестовое устройство
DEVICES = {
    "lamp_1": {
        "id": "lamp_1",
        "name": "Лампа",
        "type": "devices.types.light",
        "state": False
    }
}

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

# ---------- Root ----------
@app.route("/", methods=["GET", "HEAD"])
def root():
    if request.method == "HEAD":
        return Response(status=200)
    return jsonify({"status": "ok", "message": "OAuth server is running"})

# ---------- Smart Home endpoints ----------
@app.route("/v1.0/user/unlink", methods=["POST", "HEAD"])
def user_unlink():
    if request.method == "HEAD":
        return "", 200
    return jsonify({"status": "ok"})

@app.route("/v1.0/user/devices", methods=["GET", "HEAD"])
def user_devices():
    if request.method == "HEAD":
        return "", 200
    return jsonify({
        "user_id": "user_001",
        "devices": list(DEVICES.values())
    })

@app.route("/v1.0/user/devices/query", methods=["POST", "HEAD"])
def devices_query():
    if request.method == "HEAD":
        return "", 200
    data = request.get_json(silent=True) or {}
    devices = data.get("devices", [])
    result_devices = []

    for device_id in devices:
        if device_id in DEVICES:
            result_devices.append({
                "id": device_id,
                "capabilities": [{
                    "type": "devices.capabilities.on_off",
                    "state": {"instance": "on", "value": DEVICES[device_id]["state"]}
                }]
            })
        else:
            result_devices.append({"id": device_id, "error_code": "DEVICE_UNREACHABLE"})
    return jsonify({"devices": result_devices})

@app.route("/v1.0/user/devices/action", methods=["POST", "HEAD"])
def devices_action():
    if request.method == "HEAD":
        return "", 200
    data = request.get_json(silent=True) or {}
    devices = data.get("devices", [])
    result_devices = []

    for device in devices:
        device_id = device.get("id")
        state = device.get("capabilities", [{}])[0].get("state", {})
        if device_id in DEVICES:
            DEVICES[device_id]["state"] = state.get("value", DEVICES[device_id]["state"])
            result_devices.append({
                "id": device_id,
                "action_result": {"status": "DONE"},
                "capabilities": [{
                    "type": "devices.capabilities.on_off",
                    "state": {"instance": "on", "value": DEVICES[device_id]["state"]}
                }]
            })
        else:
            result_devices.append({
                "id": device_id,
                "action_result": {"status": "ERROR", "error_code": "DEVICE_UNREACHABLE"}
            })
    return jsonify({"devices": result_devices})

# Общий endpoint для discovery, query и action
# ---------- Smart Home endpoints ----------
@app.route("/v1.0", methods=["POST", "HEAD"])
def yandex_dialog():
    if request.method == "HEAD":
        return Response(status=200)

    body = request.get_json(silent=True) or {}
    request_id = body.get("headers", {}).get("request_id", "") or request.headers.get("X-Request-Id", "")

    # ---------- Discovery ----------

    if body.get("request_type") == "discovery":
        headers = body.get("headers", {})
    request_id = headers.get("request_id", "unknown")
    return jsonify({
        "request_id": request_id,
        "payload": {
            "user_id": "admin",
            "devices": [
                {
                    "id": "lamp_1",
                    "name": "Лампа",
                    "description": "цветная лампа",
                    "room": "спальня",
                    "type": "devices.types.light",
                    "custom_data": {
                        "foo": 1,
                        "bar": "two",
                        "baz": False,
                        "qux": [1, "two", False],
                        "quux": {"quuz": {"corge": []}}
                    },
                    "capabilities": [
                        {
                            "type": "devices.capabilities.on_off",
                            "retrievable": True,
                            "reportable": True
                        },
                        {
                            "type": "devices.capabilities.range",
                            "retrievable": True,
                            "reportable": True,
                            "parameters": {
                                "instance": "brightness",
                                "unit": "unit.percent",
                                "range": {"min": 0, "max": 100, "precision": 1}
                            }
                        },
                        {
                            "type": "devices.capabilities.color_setting",
                            "retrievable": True,
                            "reportable": True,
                            "parameters": {
                                "color_model": "hsv",
                                "temperature_k": {"min": 2700, "max": 9000, "precision": 1}
                            }
                        }
                    ],
                    "device_info": {
                        "manufacturer": "Provider2",
                        "model": "hue g11",
                        "hw_version": "1.2",
                        "sw_version": "5.4"
                    }
                }
            ]
        }
    })
    
    # ---------- Query / Action ----------
    user = get_user_by_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # query
    if body.get("request_type") == "query":
        devices = body.get("payload", {}).get("devices", [])
        result_devices = []
        for item in devices:
            device_id = item.get("id")
            if device_id in DEVICES:
                dev = DEVICES[device_id]
                result_devices.append({
                    "id": device_id,
                    "capabilities": [
                        {"type": "devices.capabilities.on_off",
                         "state": {"instance": "on", "value": dev["state"]}}
                    ]
                })
            else:
                result_devices.append({"id": device_id, "error_code": "DEVICE_UNREACHABLE"})
        return jsonify({"request_id": request_id, "payload": {"devices": result_devices}})

    # action
    if body.get("request_type") == "action":
        devices = body.get("payload", {}).get("devices", [])
        result_devices = []
        for item in devices:
            device_id = item.get("id")
            capabilities = item.get("capabilities", [])
            if device_id not in DEVICES:
                result_devices.append({
                    "id": device_id,
                    "action_result": {"status": "ERROR", "error_code": "DEVICE_UNREACHABLE"}
                })
                continue
            dev = DEVICES[device_id]
            for cap in capabilities:
                if cap.get("type") == "devices.capabilities.on_off":
                    dev["state"] = bool(cap.get("state", {}).get("value", dev["state"]))
            result_devices.append({
                "id": device_id,
                "action_result": {"status": "DONE"},
                "capabilities": [
                    {"type": "devices.capabilities.on_off", "state": {"instance": "on", "value": dev["state"]}}
                ]
            })
        return jsonify({"request_id": request_id, "payload": {"devices": result_devices}})

    # default fallback
    return jsonify({"request_id": request_id, "payload": {"devices": []}})
# ---------- OAuth ----------
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
        if redirect_uri != YANDEX_REDIRECT_URI:
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
    if redirect_uri != YANDEX_REDIRECT_URI:
        return Response("Invalid redirect_uri", status=400)
    if username != TEST_USERNAME or password != TEST_PASSWORD:
        return Response("Неверный логин или пароль", status=401)

    code = secrets.token_urlsafe(32)
    AUTH_CODES[code] = {"username": username, "client_id": client_id, "scope": scope, "expires_at": int(time.time()) + CODE_TTL_SECONDS, "used": False}
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

    return jsonify({"access_token": access_token, "token_type": "bearer", "expires_in": ACCESS_TTL_SECONDS, "refresh_token": refresh_token, "scope": code_data["scope"]})

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
    return jsonify({"access_token": new_access_token, "token_type": "bearer", "expires_in": ACCESS_TTL_SECONDS, "refresh_token": refresh_token, "scope": "basic"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)