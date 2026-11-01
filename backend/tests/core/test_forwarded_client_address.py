"""
The per-IP rate limits key on the caller's address. Behind the bundled Caddy, which is another
container, that address only arrives in `X-Forwarded-For`, and uvicorn honours the header only from
the addresses in `FORWARDED_ALLOW_IPS`. `start.sh` sets that default, so these tests run uvicorn's
own proxy-headers middleware with the value `start.sh` hands it.
"""

import re
import subprocess
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI, Request
from slowapi.util import get_remote_address
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

START_SH = Path(__file__).resolve().parents[2] / "start.sh"


def start_sh_forwarded_allow_ips(env_value: str | None = None) -> str:
    """What `start.sh` exports as FORWARDED_ALLOW_IPS, with the script's `uvicorn` exec stubbed out."""
    script = START_SH.read_text().replace("python -m alembic upgrade head", ":")
    script = re.sub(r"^exec uvicorn.*$", 'printf %s "$FORWARDED_ALLOW_IPS"', script, flags=re.M)
    env = {"PATH": "/usr/bin:/bin"}
    if env_value is not None:
        env["FORWARDED_ALLOW_IPS"] = env_value
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env, check=True
    )
    return result.stdout


async def limiter_key(peer: str, forwarded_for: str, trusted: str) -> str:
    app = FastAPI()

    @app.get("/key")
    def key(request: Request) -> str:
        return get_remote_address(request)

    wrapped = cast(Any, ProxyHeadersMiddleware(cast(Any, app), trusted_hosts=trusted))
    transport = httpx.ASGITransport(app=wrapped, client=(peer, 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/key", headers={"X-Forwarded-For": forwarded_for})
    return response.json()


@pytest.mark.parametrize("web_container", ["172.18.0.5", "10.0.3.2", "192.168.16.4"])
async def test_limiter_keys_on_the_caller_behind_the_web_container(web_container):
    trusted = start_sh_forwarded_allow_ips()

    assert await limiter_key(web_container, "203.0.113.7", trusted) == "203.0.113.7"


async def test_limiter_ignores_a_forwarded_address_from_a_public_peer():
    trusted = start_sh_forwarded_allow_ips()

    assert await limiter_key("198.51.100.9", "203.0.113.7", trusted) == "198.51.100.9"


async def test_a_self_hoster_can_override_the_trusted_range():
    trusted = start_sh_forwarded_allow_ips("172.30.0.0/16")

    assert trusted == "172.30.0.0/16"
