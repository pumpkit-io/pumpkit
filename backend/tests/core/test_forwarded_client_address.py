"""Behind the bundled Caddy, the per-IP rate limits key on the caller from `X-Forwarded-For`."""

import subprocess
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from slowapi.util import get_remote_address

START_SH = Path(__file__).resolve().parents[2] / "start.sh"


def start_sh_forwarded_allow_ips(tmp_path: Path) -> str:
    """The FORWARDED_ALLOW_IPS `start.sh` launches uvicorn with, captured by a stub `uvicorn` on PATH."""
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name, body in {
        "python": "exit 0",
        "uvicorn": 'printf %s "$FORWARDED_ALLOW_IPS" > "$CAPTURE"',
    }.items():
        stub = stubs / name
        stub.write_text(f"#!/bin/sh\n{body}\n")
        stub.chmod(0o755)
    capture = tmp_path / "uvicorn-env"
    subprocess.run(
        ["bash", str(START_SH)],
        env={"PATH": f"{stubs}:/usr/bin:/bin", "CAPTURE": str(capture)},
        check=True,
    )
    return capture.read_text()


async def limiter_key(peer: str, forwarded_for: str, tmp_path: Path, monkeypatch) -> str:
    """The key the limiter uses for a request from `peer`, through uvicorn as `start.sh` configures it."""
    app = FastAPI()

    @app.get("/key")
    def key(request: Request) -> str:
        return get_remote_address(request)

    monkeypatch.setenv("FORWARDED_ALLOW_IPS", start_sh_forwarded_allow_ips(tmp_path))
    config = uvicorn.Config(app)
    config.load()
    transport = httpx.ASGITransport(app=cast(Any, config.loaded_app), client=(peer, 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/key", headers={"X-Forwarded-For": forwarded_for})
    return response.json()


@pytest.mark.parametrize("web_container", ["172.18.0.5", "10.0.3.2", "192.168.16.4"])
async def test_limiter_keys_on_the_caller_behind_the_web_container(
    web_container, tmp_path, monkeypatch
):
    key = await limiter_key(web_container, "203.0.113.7", tmp_path, monkeypatch)

    assert key == "203.0.113.7"


async def test_limiter_ignores_a_forwarded_address_from_a_public_peer(tmp_path, monkeypatch):
    key = await limiter_key("198.51.100.9", "203.0.113.7", tmp_path, monkeypatch)

    assert key == "198.51.100.9"
