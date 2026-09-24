from io import BytesIO

from polyptich.www import AccessIdentity, create_app
from polyptich.www.auth import AccessVerificationError


class FakeVerifier:
    def verify(self, token):
        if not token or "@" not in token:
            raise AccessVerificationError("test token is invalid")
        return AccessIdentity(
            subject="subject-" + token,
            email=token,
            issuer="https://access.example.test",
            audience="polyptich",
            expires_at=2**31 - 1,
        )


def auth(email):
    return {"Cf-Access-Jwt-Assertion": email}


def test_file_upload_and_confirmed_deletion_are_operator_only(tmp_path):
    documents = tmp_path / "www" / "documents"
    documents.mkdir(parents=True)
    protected_directory = documents / "keep"
    protected_directory.mkdir()
    app = create_app(
        tmp_path,
        access_verifier=FakeVerifier(),
        operator_emails=["operator@example.test"],
    )
    client = app.test_client()
    token = app.config["POLYPTICH_WWW_FILE_CONTROL_TOKEN"]

    denied = client.post(
        "/upload/documents",
        headers=auth("reader@example.test"),
        data={"csrf_token": token, "files": (BytesIO(b"denied"), "denied.txt")},
    )
    assert denied.status_code == 403
    assert not (documents / "denied.txt").exists()

    uploaded = client.post(
        "/upload/documents",
        headers=auth("operator@example.test"),
        data={
            "csrf_token": token,
            "files": [
                (BytesIO(b"first"), "first.txt"),
                (BytesIO(b"second"), "second.txt"),
            ],
        },
    )
    assert uploaded.status_code == 302
    assert (documents / "first.txt").read_bytes() == b"first"
    assert (documents / "second.txt").read_bytes() == b"second"

    collision = client.post(
        "/upload/documents",
        headers=auth("operator@example.test"),
        data={"csrf_token": token, "files": (BytesIO(b"replacement"), "first.txt")},
    )
    assert collision.status_code == 409
    assert (documents / "first.txt").read_bytes() == b"first"

    unconfirmed = client.post(
        "/delete/documents/first.txt",
        headers=auth("operator@example.test"),
        data={"csrf_token": token},
    )
    assert unconfirmed.status_code == 400
    assert (documents / "first.txt").exists()

    deleted = client.post(
        "/delete/documents/first.txt",
        headers=auth("operator@example.test"),
        data={"csrf_token": token, "confirmed": "yes"},
    )
    assert deleted.status_code == 302
    assert not (documents / "first.txt").exists()

    directory_delete = client.post(
        "/delete/documents/keep",
        headers=auth("operator@example.test"),
        data={"csrf_token": token, "confirmed": "yes"},
    )
    assert directory_delete.status_code == 400
    assert protected_directory.is_dir()


def test_file_controls_reject_invalid_tokens_and_upload_names(tmp_path):
    documents = tmp_path / "www" / "documents"
    documents.mkdir(parents=True)
    app = create_app(
        tmp_path,
        access_verifier=FakeVerifier(),
        operator_emails=["operator@example.test"],
    )
    client = app.test_client()

    invalid_token = client.post(
        "/upload/documents",
        headers=auth("operator@example.test"),
        data={"csrf_token": "invalid", "files": (BytesIO(b"data"), "file.txt")},
    )
    assert invalid_token.status_code == 403

    invalid_name = client.post(
        "/upload/documents",
        headers=auth("operator@example.test"),
        data={
            "csrf_token": app.config["POLYPTICH_WWW_FILE_CONTROL_TOKEN"],
            "files": (BytesIO(b"data"), "../outside.txt"),
        },
    )
    assert invalid_name.status_code == 400
    assert not (tmp_path / "www" / "outside.txt").exists()
