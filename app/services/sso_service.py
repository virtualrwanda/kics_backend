"""
Microsoft 365 / Azure AD SSO service.

NOTE: If authlib is not installed, SSO endpoints return 503.
Install with: pip install authlib httpx
"""

import logging
from typing import Optional, Dict, Any

from ..core.config import settings

logger = logging.getLogger(__name__)


# Optional import with graceful fallback
try:
    import httpx
    from authlib.integrations.httpx_client import AsyncOAuth2Client
    SSO_AVAILABLE = True
except ImportError:
    logger.warning("SSO disabled: 'authlib' or 'httpx' not installed")
    SSO_AVAILABLE = False
    httpx = None  # type: ignore
    AsyncOAuth2Client = None  # type: ignore


def _azure_metadata_url() -> str:
    return (
        f"{settings.AZURE_AUTHORITY}/"
        f"{settings.AZURE_TENANT_ID}/v2.0/.well-known/openid-configuration"
    )


async def _get_openid_config() -> Optional[Dict[str, Any]]:
    if not SSO_AVAILABLE:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(_azure_metadata_url())
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.error(f"Failed to fetch OpenID config: {e}")
        return None


async def get_authorization_url(state: str = "kics") -> str:
    if not SSO_AVAILABLE:
        raise RuntimeError("SSO unavailable: install 'authlib' package")
    if not settings.AZURE_CLIENT_ID or not settings.AZURE_TENANT_ID:
        raise RuntimeError("Azure AD SSO is not configured")
    config = await _get_openid_config()
    if not config:
        raise RuntimeError("Cannot reach Microsoft OpenID endpoint")
    async with AsyncOAuth2Client(
        client_id=settings.AZURE_CLIENT_ID,
        client_secret=settings.AZURE_CLIENT_SECRET,
        scope="openid email profile User.Read",
        redirect_uri=settings.AZURE_REDIRECT_URI,
    ) as client:
        uri, _ = client.create_authorization_url(
            config["authorization_endpoint"], state=state
        )
        return uri


async def exchange_code_for_token(code: str) -> Optional[Dict[str, Any]]:
    if not SSO_AVAILABLE:
        return None
    if not settings.AZURE_CLIENT_ID or not settings.AZURE_CLIENT_SECRET:
        logger.error("Azure credentials not configured")
        return None
    config = await _get_openid_config()
    if not config:
        return None
    async with AsyncOAuth2Client(
        client_id=settings.AZURE_CLIENT_ID,
        client_secret=settings.AZURE_CLIENT_SECRET,
        redirect_uri=settings.AZURE_REDIRECT_URI,
    ) as client:
        try:
            token = await client.fetch_token(
                config["token_endpoint"],
                code=code,
                grant_type="authorization_code",
            )
        except Exception as e:
            logger.error(f"Token exchange failed: {e}")
            return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                config["userinfo_endpoint"],
                headers={"Authorization": f"Bearer {token['access_token']}"},
            )
            r.raise_for_status()
            userinfo = r.json()
    except Exception as e:
        logger.error(f"Failed to fetch user info: {e}")
        return None
    email = (
        userinfo.get("email")
        or userinfo.get("preferred_username")
        or userinfo.get("upn")
    )
    if not email:
        logger.warning(f"No email in userinfo: {userinfo}")
        return None
    return {
        "email": email.lower(),
        "name": userinfo.get("name") or userinfo.get("given_name") or email.split("@")[0],
        "sub": userinfo.get("sub"),
        "raw": userinfo,
    }