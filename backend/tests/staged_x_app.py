"""Local browser fixture for the prepared X routes, never imported by production assembly."""

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from slowapi.errors import RateLimitExceeded

from pumpkit.auth.router import router as auth_router
from pumpkit.connected_apps.router import rate_limit_exceeded_handler
from pumpkit.core.config import settings
from pumpkit.core.errors import register_exception_handlers
from pumpkit.core.logging import redact_access_log_paths
from pumpkit.core.photos import _to_data_url, get_photo_fetcher
from pumpkit.core.rate_limit import limiter
from pumpkit.x_connection.sign_in_router import router as sign_in_router

_START = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local X sign-in test</title><h1>Local X sign-in test</h1>
<button id="start">Continue with X</button><p role="status" id="status"></p>
<script>
document.querySelector('#start').onclick = async function () {
  this.disabled = true;
  document.querySelector('#status').textContent = 'Opening X…';
  const response = await fetch('/api/v1/login/x');
  const data = await response.json();
  if (response.ok) location.assign(data.url);
  else document.querySelector('#status').textContent = data.detail;
};
</script></html>"""

_CALLBACK = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local X callback</title><h1>Local X callback</h1>
<p role="status" id="status">Signing in…</p><pre id="profile"></pre><a href="/">Retry</a>
<script>
(async () => {
  const params = new URLSearchParams(location.search);
  history.replaceState(null, '', location.pathname);
  const response = await fetch('/api/v1/login/x/complete', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({state: params.get('state'), code: params.get('code'), error: params.get('error')})
  });
  const data = await response.json();
  if (!response.ok) { document.querySelector('#status').textContent = data.detail; return; }
  const profile = await (await fetch('/api/v1/users/me', {
    headers: {'Authorization': 'Bearer ' + data.access_token}
  })).json();
  document.querySelector('#status').textContent = 'Signed in';
  document.querySelector('#profile').textContent = JSON.stringify({id:profile.id, email:profile.email, handle:profile.x_handle, name:profile.first_name, hasPhoto:Boolean(profile.avatar_data_url)});
})();
</script></html>"""


class LocalPhotoFetcher:
    async def fetch(self, url: str) -> str | None:
        if url != f"{settings.X_API_URL}/_pumpkit/avatar.png":
            return None
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(url)
            if response.status_code != 200:
                return None
            return _to_data_url(response.content)
        except Exception:
            return None


def create_app() -> FastAPI:
    if settings.ENV != "local" or not settings.X_API_URL or not settings.X_AUTHORIZE_URL:
        raise RuntimeError("The staged X browser assembly requires the explicit local provider.")
    staged = FastAPI()
    staged.dependency_overrides[get_photo_fetcher] = LocalPhotoFetcher
    staged.state.limiter = limiter
    staged.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # pyright: ignore[reportArgumentType]
    register_exception_handlers(staged)
    staged.include_router(sign_in_router, prefix="/api/v1")
    staged.include_router(auth_router, prefix="/api/v1")
    redact_access_log_paths("/oauth/x/callback")

    @staged.get("/", response_class=HTMLResponse)
    async def start_page():
        return HTMLResponse(_START, headers={"Cache-Control": "no-store"})

    @staged.get("/oauth/x/callback", response_class=HTMLResponse)
    async def callback_page():
        return HTMLResponse(_CALLBACK, headers={"Cache-Control": "no-store"})

    return staged
