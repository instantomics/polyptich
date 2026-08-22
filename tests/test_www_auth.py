import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from polyptich.www import (
    AccessConfig,
    CloudflareAccessVerifier,
    LoopbackDeveloperAccessVerifier,
)
from polyptich.www.auth import AccessVerificationError


def test_access_verifier_checks_signature_issuer_audience_and_expiry():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    config = AccessConfig(
        issuer="https://access.example.test",
        audience="polyptich-audience",
    )
    verifier = CloudflareAccessVerifier(
        config,
        jwks_client=SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=public_key)
        ),
    )
    now = int(time.time())
    claims = {
        "iss": config.issuer,
        "aud": config.audience,
        "sub": "viewer-subject",
        "email": "viewer@example.test",
        "iat": now,
        "exp": now + 300,
    }

    def encode(**changes):
        return jwt.encode(
            {**claims, **changes}, private_key, algorithm="RS256", headers={"kid": "key-1"}
        )

    identity = verifier.verify(encode())
    assert identity.email == "viewer@example.test"
    assert identity.subject == "viewer-subject"
    for token in [
        encode(aud="wrong-audience"),
        encode(iss="https://attacker.example.test"),
        encode(exp=now - 1),
    ]:
        with pytest.raises(AccessVerificationError):
            verifier.verify(token)

    forged_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(claims, forged_key, algorithm="RS256", headers={"kid": "key-1"})
    with pytest.raises(AccessVerificationError):
        verifier.verify(forged)


def test_access_configuration_and_app_reject_unauthenticated_setup(tmp_path):
    with pytest.raises(ValueError, match="HTTPS origin"):
        AccessConfig(issuer="http://access.example.test", audience="polyptich")
    with pytest.raises(ValueError, match="without a path"):
        AccessConfig(issuer="https://access.example.test/team", audience="polyptich")
    with pytest.raises(ValueError, match="must not be empty"):
        AccessConfig(issuer="https://access.example.test", audience="")

    from polyptich.www import create_app

    with pytest.raises(ValueError, match="Access configuration or an Access verifier"):
        create_app(tmp_path)


def test_loopback_developer_verifier_requires_exact_strong_key():
    verifier = LoopbackDeveloperAccessVerifier(
        "a" * 64, email="developer@example.test"
    )

    identity = verifier.verify("a" * 64)

    assert identity.email == "developer@example.test"
    assert identity.issuer == "polyptich://loopback-developer"
    for token in ("", "b" * 64, "é" * 64):
        with pytest.raises(AccessVerificationError):
            verifier.verify(token)
    with pytest.raises(ValueError, match="at least 32"):
        LoopbackDeveloperAccessVerifier("short")
