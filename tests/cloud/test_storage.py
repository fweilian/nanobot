from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from types import SimpleNamespace

_STORAGE_PATH = Path(__file__).resolve().parents[2] / "nanobot" / "cloud" / "storage.py"
_SPEC = importlib.util.spec_from_file_location("nanobot_cloud_storage_under_test", _STORAGE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

_content_md5_header = _MODULE._content_md5_header
_ensure_delete_objects_content_md5 = _MODULE._ensure_delete_objects_content_md5
create_s3_client = _MODULE.create_s3_client


def test_create_s3_client_registers_delete_objects_md5_hook(monkeypatch):
    class FakeEvents:
        def __init__(self):
            self.registrations: list[tuple[str, object]] = []

        def register(self, event_name: str, handler: object) -> None:
            self.registrations.append((event_name, handler))

    fake_client = SimpleNamespace(meta=SimpleNamespace(events=FakeEvents()))
    boto3_calls: list[tuple[str, dict[str, str]]] = []

    def fake_boto3_client(service_name: str, **kwargs: str):
        boto3_calls.append((service_name, kwargs))
        return fake_client

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=fake_boto3_client))

    client = create_s3_client(
        endpoint_url="http://localhost:9000",
        region_name="us-east-1",
        access_key_id="key",
        secret_access_key="secret",
    )

    assert client is fake_client
    assert boto3_calls == [
        (
            "s3",
            {
                "endpoint_url": "http://localhost:9000",
                "region_name": "us-east-1",
                "aws_access_key_id": "key",
                "aws_secret_access_key": "secret",
            },
        )
    ]
    assert fake_client.meta.events.registrations == [
        ("before-sign.s3.DeleteObjects", _ensure_delete_objects_content_md5)
    ]


def test_ensure_delete_objects_content_md5_uses_request_body_bytes():
    body = b"<Delete><Object><Key>demo.txt</Key></Object><Quiet>true</Quiet></Delete>"
    request = SimpleNamespace(body=body, headers={})

    _ensure_delete_objects_content_md5(request)

    assert request.headers["Content-MD5"] == _content_md5_header(body)


def test_ensure_delete_objects_content_md5_preserves_stream_position():
    body = b"<Delete><Object><Key>stream.txt</Key></Object></Delete>"
    stream = io.BytesIO(body)
    stream.seek(7)
    request = SimpleNamespace(body=stream, headers={})

    _ensure_delete_objects_content_md5(request)

    assert request.headers["Content-MD5"] == _content_md5_header(body[7:])
    assert stream.tell() == 7
