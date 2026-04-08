"""FastAPI application factory."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from cogamer.api.routes import router
from cogamer.auth import AuthenticatedCogamer, validate_softmax_token


def _resolve_cogamer_token(token: str) -> AuthenticatedCogamer | None:
    """Look up a cgm_ token in DynamoDB, return cogamer identity or None."""
    from cogamer.api.routes import get_db

    db = get_db()
    # Scan META items for matching token
    # TODO: add a GSI on token for O(1) lookup if scale demands it
    cogamers = db.list_cogamers()
    for c in cogamers:
        if c.token == token:
            return AuthenticatedCogamer(cogamer_name=c.name)
    return None


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "missing bearer token"})
        token = auth_header.removeprefix("Bearer ").strip()

        if token.startswith("cgm_"):
            caller = _resolve_cogamer_token(token)
        else:
            caller = validate_softmax_token(token)

        if caller is None:
            return JSONResponse(status_code=401, content={"detail": "invalid token"})
        request.state.caller = caller
        return await call_next(request)


def create_app() -> FastAPI:
    app = FastAPI(title="Cogamer", version="0.1.0")
    app.add_middleware(AuthMiddleware)
    app.include_router(router)

    from fastapi_mcp import FastApiMCP

    mcp = FastApiMCP(app, name="cogamer", description="Cogamer agent platform")
    mcp.mount_http()

    return app


app = create_app()
