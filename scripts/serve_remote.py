from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import sys
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

COOKIE_NAME = "forge3d_session"
SESSION_MAX_AGE = 8 * 60 * 60
LOGIN_PATH = "/_auth/login"
LOGOUT_PATH = "/_auth/logout"


def _session_signature(secret: bytes, expires_at: str) -> str:
    digest = hmac.new(secret, b"forge3d-session:" + expires_at.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _login_page(message: str = "") -> bytes:
    safe_message = (
        '<p class="error" role="alert">Token inválido. Tente novamente.</p>' if message else ""
    )
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Forge3D · Acesso privado</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    body {{ min-height: 100vh; margin: 0; display: grid; place-items: center; background: #101116; color: #eeeef2; }}
    main {{ width: min(24rem, calc(100vw - 3rem)); padding: 2rem; border: 1px solid #343640; border-radius: 1rem; background: #191a22; box-shadow: 0 24px 80px #0008; }}
    h1 {{ margin: 0; font-size: 1.35rem; letter-spacing: -.03em; }}
    p {{ color: #aaabb6; line-height: 1.55; }}
    label {{ display: block; margin: 1.5rem 0 .5rem; font-size: .9rem; }}
    input {{ box-sizing: border-box; width: 100%; padding: .8rem .9rem; border: 1px solid #454752; border-radius: .55rem; background: #111219; color: inherit; font: inherit; }}
    input:focus {{ outline: 2px solid #8974ee; outline-offset: 2px; }}
    button {{ width: 100%; margin-top: 1rem; padding: .8rem; border: 0; border-radius: .55rem; background: #8068ed; color: white; font: inherit; font-weight: 650; cursor: pointer; }}
    button:hover {{ background: #937ff4; }}
    .error {{ color: #ff9a9a; }}
  </style>
</head>
<body>
  <main>
    <h1>Forge3D</h1>
    <p>Acesso privado ao workspace. Informe o token de acesso para abrir a interface.</p>
    {safe_message}
    <form method="post" action="{LOGIN_PATH}" autocomplete="off">
      <label for="token">Token de acesso</label>
      <input id="token" name="token" type="password" required minlength="32" autocomplete="current-password" autofocus>
      <button type="submit">Entrar</button>
    </form>
  </main>
</body>
</html>""".encode("utf-8")


class AccessGateway:
    """Protect the UI, API, generated files, and streaming responses at ASGI ingress."""

    def __init__(self, app, access_token: str) -> None:
        if len(access_token) < 32 or not access_token.isascii():
            raise RuntimeError("FORGE3D_ACCESS_TOKEN deve ter ao menos 32 caracteres ASCII.")
        self.app = app
        self.secret = access_token.encode("ascii")
        self.expected_token = access_token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")
        method = scope.get("method", "GET").upper()
        headers = {key.lower(): value for key, value in scope.get("headers", [])}

        if path == LOGIN_PATH:
            if method == "GET":
                await self._send(send, 200, _login_page(), "text/html; charset=utf-8", [(b"cache-control", b"no-store")])
                return
            if method == "POST":
                await self._login(scope, receive, send, headers)
                return
            await self._send(send, 405, b"Method Not Allowed", "text/plain; charset=utf-8", [(b"allow", b"GET, POST")])
            return

        if path == LOGOUT_PATH and method == "POST":
            secure = self._is_https(headers)
            cookie = f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
            if secure:
                cookie += "; Secure"
            await self._send(
                send,
                303,
                b"",
                "text/plain; charset=utf-8",
                [(b"location", LOGIN_PATH.encode("ascii")), (b"set-cookie", cookie.encode("ascii")), (b"cache-control", b"no-store")],
            )
            return

        if not self._authorized(headers):
            accept = headers.get(b"accept", b"").lower()
            if method in {"GET", "HEAD"} and b"text/html" in accept and path != "/api" and not path.startswith("/api/"):
                await self._send(
                    send,
                    303,
                    b"",
                    "text/plain; charset=utf-8",
                    [(b"location", LOGIN_PATH.encode("ascii")), (b"cache-control", b"no-store")],
                )
                return
            await self._send(
                send,
                401,
                b'{"detail":"Authentication required"}',
                "application/json",
                [(b"www-authenticate", b'Bearer realm="Forge3D"'), (b"cache-control", b"no-store")],
            )
            return

        async def secured_send(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                names = {key.lower() for key, _ in response_headers}
                if b"x-content-type-options" not in names:
                    response_headers.append((b"x-content-type-options", b"nosniff"))
                if b"referrer-policy" not in names:
                    response_headers.append((b"referrer-policy", b"no-referrer"))
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, secured_send)

    def _authorized(self, headers: dict[bytes, bytes]) -> bool:
        authorization = headers.get(b"authorization", b"")
        try:
            scheme, _, candidate = authorization.decode("ascii").partition(" ")
        except UnicodeDecodeError:
            candidate = ""
            scheme = ""
        if scheme.casefold() == "bearer" and hmac.compare_digest(candidate.strip(), self.expected_token):
            return True

        raw_cookie = headers.get(b"cookie", b"")
        try:
            parsed_cookie = SimpleCookie()
            parsed_cookie.load(raw_cookie.decode("latin-1"))
            session = parsed_cookie.get(COOKIE_NAME)
        except Exception:
            session = None
        if session is None:
            return False

        expires_at, separator, signature = session.value.partition(".")
        if not separator or len(expires_at) > 12 or len(signature) != 43 or not expires_at.isdigit():
            return False
        try:
            expiry = int(expires_at)
        except ValueError:
            return False
        now = int(time.time())
        if expiry <= now or expiry > now + SESSION_MAX_AGE:
            return False
        return hmac.compare_digest(signature, _session_signature(self.secret, expires_at))

    async def _login(self, scope, receive, send, headers: dict[bytes, bytes]) -> None:
        if not self._same_origin(scope, headers):
            await self._send(send, 403, b"Origin check failed", "text/plain; charset=utf-8")
            return

        content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
        if content_type != b"application/x-www-form-urlencoded":
            await self._send(send, 415, b"Expected form data", "text/plain; charset=utf-8")
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 4096:
                await self._send(send, 413, b"Request too large", "text/plain; charset=utf-8")
                return
            if not message.get("more_body", False):
                break

        try:
            values = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=8)
        except (UnicodeDecodeError, ValueError):
            values = {}
        candidate = values.get("token", [""])[0]
        if not candidate.isascii() or not hmac.compare_digest(candidate, self.expected_token):
            await self._send(
                send,
                401,
                _login_page("invalid"),
                "text/html; charset=utf-8",
                [(b"cache-control", b"no-store")],
            )
            return

        expires_at = str(int(time.time()) + SESSION_MAX_AGE)
        cookie_value = f"{expires_at}.{_session_signature(self.secret, expires_at)}"
        cookie = f"{COOKIE_NAME}={cookie_value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_MAX_AGE}"
        if self._is_https(headers):
            cookie += "; Secure"
        await self._send(
            send,
            303,
            b"",
            "text/plain; charset=utf-8",
            [(b"location", b"/"), (b"set-cookie", cookie.encode("ascii")), (b"cache-control", b"no-store")],
        )

    @staticmethod
    def _same_origin(scope, headers: dict[bytes, bytes]) -> bool:
        origin = headers.get(b"origin")
        if not origin:
            return True
        try:
            origin_text = origin.decode("ascii")
            scheme, authority = origin_text.split("://", 1)
            authority = authority.split("/", 1)[0].split("?", 1)[0].lower()
        except (UnicodeDecodeError, ValueError):
            return False
        forwarded_host = headers.get(b"x-forwarded-host", b"").split(b",", 1)[0].strip()
        host = (forwarded_host or headers.get(b"host", b"")).decode("latin-1").lower()
        forwarded_proto = headers.get(b"x-forwarded-proto", b"").split(b",", 1)[0].strip().lower()
        expected_scheme = forwarded_proto.decode("latin-1") if forwarded_proto else scope.get("scheme", "http")
        return bool(host and authority == host and scheme.lower() == expected_scheme.lower())

    @staticmethod
    def _is_https(headers: dict[bytes, bytes]) -> bool:
        forwarded_proto = headers.get(b"x-forwarded-proto", b"").split(b",", 1)[0].strip().lower()
        return forwarded_proto == b"https"

    @staticmethod
    async def _send(send, status: int, body: bytes, media_type: str, headers=()) -> None:
        response_headers = [(b"content-type", media_type.encode("ascii")), (b"content-length", str(len(body)).encode("ascii"))]
        response_headers.extend(headers)
        await send({"type": "http.response.start", "status": status, "headers": response_headers})
        await send({"type": "http.response.body", "body": body})


def create_remote_app(*, api_app=None, static_directory: Path | None = None, access_token: str | None = None):
    if api_app is None:
        from app.main import create_app

        api_app = create_app()
    distribution = Path(static_directory) if static_directory is not None else PROJECT_ROOT / "frontend" / "dist"
    if not (distribution / "index.html").is_file():
        raise RuntimeError(
            "Frontend build ausente. Execute npm install e VITE_API_BASE_URL=/api npm run build em frontend/."
        )
    static_files = StaticFiles(directory=str(distribution), html=True, check_dir=True)

    async def serve_frontend(request: Request):
        asset_path = request.path_params.get("path", "")
        if asset_path == "api" or asset_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return await static_files.get_response(asset_path, request.scope)

    api_app.add_api_route("/{path:path}", serve_frontend, methods=["GET", "HEAD"], include_in_schema=False)
    api_app.add_api_route("/", serve_frontend, methods=["GET", "HEAD"], include_in_schema=False)

    token = access_token if access_token is not None else os.environ.get("FORGE3D_ACCESS_TOKEN", "")
    return AccessGateway(api_app, token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve protected Forge3D UI and API from one local origin.")
    parser.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("FORGE3D_PORT", "7860")))
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(create_remote_app(), host=args.host, port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
