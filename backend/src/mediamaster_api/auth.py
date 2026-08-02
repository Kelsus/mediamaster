import os
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient

from . import db

_jwks_client: Optional[PyJWKClient] = None


def _issuer() -> str:
    region = os.environ.get("AWS_REGION", "us-east-1")  # set automatically in Lambda
    pool_id = os.environ["USER_POOL_ID"]
    return f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(f"{_issuer()}/.well-known/jwks.json", cache_keys=True)
    return _jwks_client


def _verify_cognito_jwt(token: str) -> str:
    signing_key = _jwks().get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=_issuer(),
        options={"verify_aud": False},  # access tokens carry client_id, not aud
    )
    if claims.get("token_use") != "access":
        raise HTTPException(401, "Not an access token")
    if claims.get("client_id") != os.environ["USER_POOL_CLIENT_ID"]:
        raise HTTPException(401, "Wrong client")
    return claims["sub"]


def current_uid(request: Request) -> str:
    """Resolve the caller to a user id from either a Cognito JWT or an mm_ API token."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = header[7:].strip()

    if token.startswith("mm_"):
        uid = db.lookup_token(token)
        if uid is None:
            raise HTTPException(401, "Invalid API token")
        return uid

    try:
        return _verify_cognito_jwt(token)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Invalid token")


def jwt_only_uid(request: Request, uid: str = Depends(current_uid)) -> str:
    """Some routes (token management) must not be reachable with an API token."""
    header = request.headers.get("authorization", "")
    if header[7:].strip().startswith("mm_"):
        raise HTTPException(403, "This endpoint requires an interactive session")
    return uid
