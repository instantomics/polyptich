from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

from flask import abort, g

DASHBOARD_READ = "dashboard.read"
AGENT_READ = "agent.read"
PRIVATE_READ = "private.read"
AGENT_CONTROL = "agent.control"
SERVICE_RESTART = "service.restart"


class AccessVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class AccessConfig:
    issuer: str
    audience: str
    jwks_url: Optional[str] = None

    def __post_init__(self):
        issuer = self.issuer.rstrip("/")
        parsed = urlparse(issuer)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path:
            raise ValueError("Access issuer must be an HTTPS origin without a path")
        if not self.audience.strip():
            raise ValueError("Access audience must not be empty")
        if self.jwks_url is not None:
            jwks = urlparse(self.jwks_url)
            if jwks.scheme != "https" or not jwks.netloc:
                raise ValueError("Access JWKS URL must use HTTPS")
        object.__setattr__(self, "issuer", issuer)

    @property
    def resolved_jwks_url(self):
        return self.jwks_url or f"{self.issuer}/cdn-cgi/access/certs"


@dataclass(frozen=True)
class AccessIdentity:
    subject: str
    email: str
    issuer: str
    audience: str
    expires_at: int


class CloudflareAccessVerifier:
    def __init__(self, config, *, jwks_client=None):
        try:
            import jwt
        except ImportError as error:
            raise RuntimeError("Install Polyptich to validate Cloudflare Access JWTs") from error
        self._jwt = jwt
        self._config = config
        self._jwks_client = jwks_client or jwt.PyJWKClient(
            config.resolved_jwks_url,
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
        )

    def verify(self, token):
        if not token:
            raise AccessVerificationError("Cloudflare Access JWT is missing")
        try:
            key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = self._jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self._config.audience,
                issuer=self._config.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except self._jwt.PyJWTError as error:
            raise AccessVerificationError("Cloudflare Access JWT is invalid") from error
        return _identity_from_claims(claims, self._config)


def current_identity():
    identity = getattr(g, "polyptich_access_identity", None)
    if identity is None:
        raise RuntimeError("No authenticated Polyptich WWW identity is active")
    return identity


def current_scopes():
    return frozenset(getattr(g, "polyptich_access_scopes", ()))


def has_scope(scope):
    return scope in current_scopes()


def require_scope(scope):
    if not has_scope(scope):
        abort(403, description=f"Required scope is missing: {scope}")


def scopes_for_email(email, *, trusted_viewer_emails=(), operator_emails=()):
    normalized = email.casefold()
    trusted = {value.casefold() for value in trusted_viewer_emails}
    operators = {value.casefold() for value in operator_emails}
    scopes = {DASHBOARD_READ, AGENT_READ}
    if normalized in trusted or normalized in operators:
        scopes.add(PRIVATE_READ)
    if normalized in operators:
        scopes.update({AGENT_CONTROL, SERVICE_RESTART})
    return frozenset(scopes)


def _identity_from_claims(claims: Mapping[str, Any], config):
    subject = claims.get("sub")
    email = claims.get("email")
    expires_at = claims.get("exp")
    if not isinstance(subject, str) or not subject:
        raise AccessVerificationError("Cloudflare Access JWT subject is invalid")
    if not isinstance(email, str) or not email:
        raise AccessVerificationError("Cloudflare Access JWT email is missing")
    if type(expires_at) is not int:
        raise AccessVerificationError("Cloudflare Access JWT expiry is invalid")
    return AccessIdentity(
        subject=subject,
        email=email,
        issuer=config.issuer,
        audience=config.audience,
        expires_at=expires_at,
    )
