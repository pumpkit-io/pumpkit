"""Registered clients (Dynamic Client Registration). Flushes, never commits."""

from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps.models import OAuthClient
from pumpkit.connected_apps.schemas import ClientRegistrationRequest
from pumpkit.core.security import generate_token, hash_token

CLIENT_SECRET_PREFIX = "pumpkit_cs_"


async def register_client(
    db: AsyncSession, metadata: ClientRegistrationRequest, *, now: datetime
) -> tuple[OAuthClient, Optional[str]]:
    """Add the client, and return it with its secret when it authenticates with one."""
    secret = None
    if metadata.token_endpoint_auth_method != "none":
        secret = CLIENT_SECRET_PREFIX + generate_token(32)
    client = OAuthClient(
        kind="registered",
        name=metadata.client_name,
        redirect_uris=metadata.redirect_uris,
        token_endpoint_auth_method=metadata.token_endpoint_auth_method,
        client_secret_hash=hash_token(secret) if secret else None,
        client_uri=metadata.client_uri,
        logo_uri=metadata.logo_uri,
        software_id=metadata.software_id,
        software_version=metadata.software_version,
        created_at=now,
    )
    db.add(client)
    await db.flush()
    return client, secret


async def get_client(db: AsyncSession, client_id: str) -> Optional[OAuthClient]:
    return await db.get(OAuthClient, client_id)
