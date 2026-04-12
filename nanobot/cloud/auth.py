"""OAuth/OIDC access token verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Header, HTTPException, status


@dataclass(slots=True)
class AuthenticatedUser:
    """Authenticated cloud user derived from an access token."""

    user_id: str
    claims: dict[str, Any]
    token: str


class TokenVerifier(Protocol):
    """Minimal token verifier contract."""

    def verify(self, token: str) -> AuthenticatedUser: ...


class JwtTokenVerifier:
    """Verify JWT access tokens with either a shared secret or a JWKS endpoint."""

    def __init__(
        self,
        *,
        algorithms: list[str],
        user_id_claim: str = "sub",
        audience: str | None = None,
        issuer: str | None = None,
        jwks_url: str | None = None,
        shared_secret: str | None = None,
    ) -> None:
        self.algorithms = algorithms
        self.user_id_claim = user_id_claim
        self.audience = audience
        self.issuer = issuer
        self.jwks_url = jwks_url
        self.shared_secret = shared_secret
        self._jwks_client = None

    def _decode(self, token: str) -> dict[str, Any]:
        import jwt

        options = {"verify_aud": self.audience is not None}
        if self.shared_secret:
            return jwt.decode(
                token,
                self.shared_secret,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self.issuer,
                options=options,
            )
        if not self.jwks_url:
            raise ValueError("Either shared_secret or jwks_url must be configured")
        if self._jwks_client is None:
            self._jwks_client = jwt.PyJWKClient(self.jwks_url)
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=self.algorithms,
            audience=self.audience,
            issuer=self.issuer,
            options=options,
        )

    def verify(self, token: str) -> AuthenticatedUser:
        try:
            claims = self._decode(token)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid access token: {exc}",
            ) from exc
        user_id = claims.get(self.user_id_claim)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Missing user id claim '{self.user_id_claim}'",
            )
        return AuthenticatedUser(user_id=str(user_id), claims=claims, token=token)


async def resolve_bearer_token(authorization: str | None = Header(default=None)) -> str:
    """Extract a bearer token from the Authorization header."""
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    return token
