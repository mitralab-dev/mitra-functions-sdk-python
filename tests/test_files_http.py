"""Storage transfers over a real httpx.HTTPTransport and a loopback server.

The API side stays on MockTransport; only the storage origin is mounted on a real transport, which
is the path HttpTransport.storage_request takes through Client._transport_for_url.
"""

import logging
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest

from mitra_functions_sdk import (
    MitraClient,
    MitraClientConfig,
    MitraFileTransferError,
    create_client,
)

TOKEN = "loopback-access-token"
UPLOAD_SIGNATURE = "loopback-upload-signature"
READ_SIGNATURE = "loopback-read-signature"
UPLOAD_TARGET = (
    "/files/tmp/tenant/tenant-1/app/app-1/file-1"
    f"?X-Amz-Credential=key&X-Amz-Signature={UPLOAD_SIGNATURE}"
)
READ_TARGET = (
    f"/files/tmp/tenant/tenant-1/app/app-1/file-1?versionId=v1&X-Amz-Signature={READ_SIGNATURE}"
)
CONTENT = b"loopback bytes\n"
FILES_PATH = "/data-manager/api/v1/files"
FILE_PATH = f"{FILES_PATH}/file-1"
# Long enough for any loopback exchange on a slow CI runner; the timeout test uses its own.
TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Received:
    method: str
    target: str
    headers: dict[str, str]
    body: bytes


Respond = Callable[[BaseHTTPRequestHandler, "LoopbackStorage"], None]


def answer(status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> Respond:
    def respond(handler: BaseHTTPRequestHandler, _storage: "LoopbackStorage") -> None:
        handler.send_response(status)
        for name, value in (headers or {}).items():
            handler.send_header(name, value)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    return respond


def never_answer(_handler: BaseHTTPRequestHandler, storage: "LoopbackStorage") -> None:
    # Holds the connection open without a status line until the test ends.
    storage.released.wait(timeout=30)


@dataclass
class LoopbackStorage:
    respond: Respond = field(default_factory=lambda: answer(200))
    received: list[Received] = field(default_factory=list)
    released: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        storage = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def handle_any(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                storage.received.append(
                    Received(
                        method=self.command,
                        target=self.path,
                        headers={name.lower(): value for name, value in self.headers.items()},
                        body=self.rfile.read(length),
                    )
                )
                storage.respond(self, storage)

            do_GET = do_PUT = do_POST = handle_any

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # shutdown() waits for the loop to notice, which by default takes up to half a second.
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()

    @property
    def origin(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host!s}:{port}"

    def url(self, target: str) -> str:
        return f"{self.origin}{target}"

    def close(self) -> None:
        self.released.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def storage() -> Iterator[LoopbackStorage]:
    server = LoopbackStorage()
    yield server
    server.close()


def api(storage: LoopbackStorage, calls: list[tuple[str, str]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if (request.method, request.url.path) == ("POST", FILES_PATH):
            return httpx.Response(
                201,
                json={
                    "fileId": "file-1",
                    "uploadUrl": storage.url(UPLOAD_TARGET),
                    "uploadMethod": "PUT",
                    "uploadHeaders": {"content-type": "text/plain", "if-none-match": "*"},
                    "expiresAt": "2026-11-14T10:05:00Z",
                },
            )
        if (request.method, request.url.path) == ("POST", f"{FILE_PATH}/confirm"):
            return httpx.Response(200, json=file_metadata())
        if (request.method, request.url.path) == ("POST", f"{FILE_PATH}/read-url"):
            return httpx.Response(
                200, json={"url": storage.url(READ_TARGET), "expiresAt": "2026-11-14T10:05:00Z"}
            )
        if (request.method, request.url.path) == ("DELETE", FILE_PATH):
            return httpx.Response(204)
        raise AssertionError(f"unexpected API request {request.method} {request.url.path}")

    return httpx.MockTransport(handler)


def file_metadata() -> dict[str, object]:
    return {
        "id": "file-1",
        "name": "notes.txt",
        "contentType": "text/plain",
        "sizeBytes": len(CONTENT),
        "kind": "TEMPORARY",
        "visibility": "PRIVATE",
        "status": "READY",
        "ownerUserId": "user-1",
        "createdBy": "USER",
        "createdAt": "2026-11-14T10:00:00Z",
        "confirmedAt": "2026-11-14T10:00:01Z",
        "expiresAt": "2026-11-21T10:00:00Z",
    }


def make_client(
    storage: LoopbackStorage,
    calls: list[tuple[str, str]],
    *,
    timeout_seconds: float = TIMEOUT_SECONDS,
    **client_options: Any,
) -> tuple[MitraClient, httpx.Client]:
    http_client = httpx.Client(
        transport=api(storage, calls),
        mounts={storage.origin: httpx.HTTPTransport()},
        **client_options,
    )
    client = create_client(
        MitraClientConfig(
            api_url="https://api.mitra.test",
            access_token=TOKEN,
            app_id="app-1",
            timeout_seconds=timeout_seconds,
            http_client=http_client,
        )
    )
    return client, http_client


def upload_notes(client: MitraClient) -> object:
    return client.files.upload(
        CONTENT,
        name="notes.txt",
        content_type="text/plain",
        kind="TEMPORARY",
        visibility="PRIVATE",
    )


def test_put_reaches_storage_with_the_bytes_and_only_the_signed_headers(
    storage: LoopbackStorage,
) -> None:
    calls: list[tuple[str, str]] = []
    client, http_client = make_client(
        storage,
        calls,
        headers={"Authorization": "Bearer client-default", "X-Client-Default": "1"},
        auth=("client-user", "client-password"),
        cookies={"session": "client-cookie"},
    )

    assert upload_notes(client) == file_metadata()

    [sent] = storage.received
    assert sent.method == "PUT"
    assert sent.target == UPLOAD_TARGET
    assert sent.body == CONTENT
    assert sent.headers == {
        "host": storage.origin.removeprefix("http://"),
        "content-length": str(len(CONTENT)),
        "content-type": "text/plain",
        "if-none-match": "*",
    }
    assert calls == [("POST", FILES_PATH), ("POST", f"{FILE_PATH}/confirm")]
    http_client.close()


def test_redirect_is_not_followed_and_the_pending_file_is_deleted(
    storage: LoopbackStorage,
) -> None:
    storage.respond = answer(307, headers={"Location": "/elsewhere"})
    calls: list[tuple[str, str]] = []
    client, http_client = make_client(storage, calls, follow_redirects=True)

    with pytest.raises(MitraFileTransferError) as caught:
        upload_notes(client)

    assert caught.value.step == "send"
    assert caught.value.status == 307
    assert caught.value.cleaned_up is True
    assert [received.target for received in storage.received] == [UPLOAD_TARGET]
    assert calls == [("POST", FILES_PATH), ("DELETE", FILE_PATH)]
    http_client.close()


def test_storage_that_never_answers_times_out_and_the_pending_file_is_deleted(
    storage: LoopbackStorage,
) -> None:
    storage.respond = never_answer
    calls: list[tuple[str, str]] = []
    client, http_client = make_client(storage, calls, timeout_seconds=0.5)

    with pytest.raises(MitraFileTransferError) as caught:
        upload_notes(client)

    assert str(caught.value) == (
        "File file-1 was not sent: the storage request timed out; the pending file was deleted"
    )
    assert caught.value.status is None
    assert caught.value.cleaned_up is True
    assert calls == [("POST", FILES_PATH), ("DELETE", FILE_PATH)]
    http_client.close()


def test_download_reads_the_content_with_no_header_but_the_host(
    storage: LoopbackStorage,
) -> None:
    storage.respond = answer(200, CONTENT)
    client, http_client = make_client(storage, [], headers={"Authorization": "Bearer default"})

    assert client.files.download("file-1") == CONTENT

    [received] = storage.received
    assert (received.method, received.target) == ("GET", READ_TARGET)
    assert received.headers == {"host": storage.origin.removeprefix("http://")}
    http_client.close()


def test_download_refused_by_storage_names_the_status(storage: LoopbackStorage) -> None:
    storage.respond = answer(404, b"<Error><Code>NoSuchKey</Code></Error>")
    client, http_client = make_client(storage, [])

    with pytest.raises(MitraFileTransferError) as caught:
        client.files.download("file-1")

    assert str(caught.value) == "File file-1 was not downloaded: storage answered 404"
    assert caught.value.status == 404
    http_client.close()


def test_debug_logs_of_httpx_and_httpcore_never_carry_the_signed_request(
    storage: LoopbackStorage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="httpx")
    caplog.set_level(logging.DEBUG, logger="httpcore")
    client, http_client = make_client(storage, [])

    upload_notes(client)
    storage.respond = answer(200, CONTENT)
    client.files.download("file-1")

    # Both loggers were captured for the storage requests: httpcore names the loopback host it
    # connected to, and httpx logged the API calls that went through the client layer.
    assert "connect_tcp.started host='127.0.0.1'" in caplog.text
    assert f"POST https://api.mitra.test{FILES_PATH}" in caplog.text
    for target in (UPLOAD_TARGET, READ_TARGET):
        path, query = target.split("?", 1)
        assert path not in caplog.text
        assert query not in caplog.text
    for signature in (UPLOAD_SIGNATURE, READ_SIGNATURE):
        assert signature not in caplog.text
    http_client.close()
