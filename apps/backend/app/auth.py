import secrets

from fastapi import Header, HTTPException, Request, status


async def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Reject requests that lack the per-session bearer token shared with the desktop app."""
    expected: str = request.app.state.settings.api_token
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )
