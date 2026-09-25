from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from gotrue.errors import AuthApiError
from pydantic import BaseModel

from auth import bearer_scheme, get_current_user
from config import supabase, PORT

app = FastAPI(
    title="FlyRank Auth API",
    version="0.1.0",
    description=(
        "Auth backend using Supabase as the identity provider.\n\n"
        "Public routes (`/public/info`, `/auth/signup`, `/auth/login`) need "
        "no token. For protected routes, log in via `POST /auth/login` to "
        "get an `access_token`, click **Authorize** above, paste the token "
        "(no `Bearer ` prefix needed), and try any protected endpoint "
        "directly from this page."
    ),
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Keeps every error response in the same {"error": ...} shape, whether
    it came from a manual check or a Depends()-raised HTTPException."""
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


class Credentials(BaseModel):
    """Optional fields so FastAPI never auto-rejects with its own 422 —
    we validate by hand below and return the spec's 400 instead."""

    email: Optional[str] = None
    password: Optional[str] = None


@app.post("/auth/signup", status_code=201)
def signup(body: Credentials):
    if not body.email or not body.password:
        return JSONResponse(
            status_code=400, content={"error": "email and password are required"}
        )

    try:
        result = supabase.auth.sign_up(
            {"email": body.email, "password": body.password}
        )
    except AuthApiError as e:
        return JSONResponse(status_code=400, content={"error": e.message})

    return JSONResponse(status_code=201, content=jsonable_encoder(result.user))


@app.post("/auth/login")
def login(body: Credentials):
    if not body.email or not body.password:
        return JSONResponse(
            status_code=400, content={"error": "email and password are required"}
        )

    try:
        result = supabase.auth.sign_in_with_password(
            {"email": body.email, "password": body.password}
        )
    except AuthApiError:
        return JSONResponse(
            status_code=401, content={"error": "Invalid login credentials"}
        )

    return JSONResponse(
        status_code=200,
        content={
            "access_token": result.session.access_token,
            "refresh_token": result.session.refresh_token,
            "user": jsonable_encoder(result.user),
        },
    )


@app.post("/auth/logout", status_code=204)
def logout(
    user=Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """Stage 4: requires a valid session (reuses the same auth dependency
    as the protected routes), then invalidates it server-side via Supabase.

    Note: supabase.auth.sign_out() operates on the SDK's own implicit
    client-side session, not an arbitrary token — wrong fit for a
    stateless server handling many users' tokens on one shared client.
    supabase.auth.admin.sign_out(jwt) instead calls the GoTrue logout
    endpoint directly with the caller's own token, which is what we want
    here."""
    try:
        supabase.auth.admin.sign_out(credentials.credentials)
    except AuthApiError:
        pass

    return Response(status_code=204)


@app.get("/public/info")
def public_info():
    """No auth required — sanity-check route for Stage 2."""
    return JSONResponse(
        status_code=200,
        content={
            "service": "FlyRank Auth API",
            "message": "This is a public endpoint, no auth required.",
        },
    )


@app.get("/protected/profile")
def protected_profile(user=Depends(get_current_user)):
    """Stage 4: auth check now comes from the shared get_current_user
    dependency instead of being hand-rolled in every route."""
    return JSONResponse(status_code=200, content={"user": jsonable_encoder(user)})


@app.get("/protected/dashboard")
def protected_dashboard(user=Depends(get_current_user)):
    """Stage 4: second protected route, proving the dependency is reusable."""
    return JSONResponse(
        status_code=200,
        content={
            "message": f"Welcome to your dashboard, {user.email}",
            "user": jsonable_encoder(user),
        },
    )


if __name__ == "__main__":
    import uvicorn

    print("Server running and connected to Supabase")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
