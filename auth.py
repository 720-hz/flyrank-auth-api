"""
Stage 4: reusable auth dependency, shared by every protected route
(/protected/profile, /protected/dashboard, /auth/logout).

Uses FastAPI's HTTPBearer security scheme (auto_error=False so we control
the error shape/status ourselves) instead of hand-parsing the Authorization
header — this also lets Stage 5 wire the same scheme into Swagger's
"Authorize" padlock with zero extra glue.
"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from gotrue.errors import AuthApiError

from config import supabase

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """Verifies the Bearer token against Supabase and returns the user.
    Raises a 401 HTTPException on any failure — reused by every protected
    route via Depends(get_current_user)."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=401, detail="Missing or malformed Authorization header"
        )

    try:
        result = supabase.auth.get_user(credentials.credentials)
    except AuthApiError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not result or not result.user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return result.user
