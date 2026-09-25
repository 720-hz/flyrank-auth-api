from typing import Optional

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from gotrue.errors import AuthApiError
from pydantic import BaseModel

from config import supabase, PORT

app = FastAPI(title="FlyRank Auth API", version="0.1.0")


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
def protected_profile(request: Request):
    """Stub for Stage 2: only checks that a well-formed Bearer header is
    present. Stage 3 replaces this with real Supabase token verification."""
    auth_header = request.headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401, content={"error": "Missing or malformed Authorization header"}
        )

    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return JSONResponse(
            status_code=401, content={"error": "Missing or malformed Authorization header"}
        )

    return JSONResponse(
        status_code=200,
        content={"message": "Token present — verification comes in Stage 3", "token_preview": token[:10] + "..."},
    )


if __name__ == "__main__":
    import uvicorn

    print("Server running and connected to Supabase")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
