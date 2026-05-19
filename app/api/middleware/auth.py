"""Azure AD / Entra ID JWT validation middleware."""
from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError
import httpx
from app.config import get_settings

_bearer = HTTPBearer(auto_error=False)
_jwks_cache: dict | None = None


async def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is None:
        s = get_settings()
        url = f"https://login.microsoftonline.com/{s.entra_tenant_id}/discovery/v2.0/keys"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            _jwks_cache = resp.json()
    return _jwks_cache


async def validate_token(request: Request) -> str:
    """Validate Azure AD JWT and return user_id. Returns 'anonymous' in dev mode."""
    s = get_settings()
    if s.is_development and not s.entra_tenant_id:
        return "dev-user"

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")

    token = auth.split(" ", 1)[1]
    try:
        jwks = await _get_jwks()
        header = jwt.get_unverified_header(token)
        key = next((k for k in jwks["keys"] if k.get("kid") == header.get("kid")), None)
        if not key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown signing key")
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=s.entra_audience or s.entra_client_id,
        )
        return claims.get("oid") or claims.get("sub") or "unknown"
    except ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")
