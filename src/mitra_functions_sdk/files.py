from __future__ import annotations

from ._http import HttpTransport, StorageResponse
from ._path import encode_path_segment
from ._response import expect_file_metadata, expect_file_read_url, expect_file_upload
from .errors import MitraFileTransferError, MitraResponseError, MitraSdkError
from .models import FileMetadata, FileReadUrl

# The API signs the upload with a media type and bytes carry none; this is the generic one.
DEFAULT_CONTENT_TYPE = "application/octet-stream"


class FilesModule:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def get(self, file_id: str) -> FileMetadata:
        return expect_file_metadata(
            self._transport.request("GET", "data-manager", _file_path(file_id)),
            "File response",
        )

    def get_url(self, file_id: str) -> FileReadUrl:
        return expect_file_read_url(
            self._transport.request("POST", "data-manager", f"{_file_path(file_id)}/read-url"),
            "File read URL response",
        )

    def download(self, file_id: str) -> bytes:
        received = self._transport.storage_request("GET", self.get_url(file_id)["url"])
        if received.failure is not None:
            raise MitraFileTransferError(
                f"File {file_id} was not downloaded: {received.failure}",
                file_id=file_id,
                step="download",
                status=received.status,
            )
        return received.content

    def upload(
        self,
        content: bytes,
        *,
        name: str,
        kind: str,
        visibility: str,
        content_type: str = DEFAULT_CONTENT_TYPE,
        app_owned: bool = False,
    ) -> FileMetadata:
        # The declared size is signed into the link. A str or bytearray would be sent with another
        # length or as a chunked stream, which storage refuses after the API has recorded the file.
        if not isinstance(content, bytes):
            raise TypeError("content must be bytes")

        file_id, sent = self._request_and_send(
            content,
            {
                "name": name,
                "contentType": content_type,
                "sizeBytes": len(content),
                "kind": kind,
                "visibility": visibility,
                "appOwned": app_owned,
            },
        )
        if sent.failure is not None:
            # The PENDING file holds one of the user's few pending slots for a day, so it goes at
            # once. A failed delete is reported in the error and never replaces the send failure.
            cleaned_up = self._delete_pending(file_id)
            outcome = (
                "the pending file was deleted"
                if cleaned_up
                else "the pending file could not be deleted"
            )
            raise MitraFileTransferError(
                f"File {file_id} was not sent: {sent.failure}; {outcome}",
                file_id=file_id,
                step="send",
                status=sent.status,
                cleaned_up=cleaned_up,
            )

        try:
            return expect_file_metadata(
                self._transport.request("POST", "data-manager", f"{_file_path(file_id)}/confirm"),
                "Confirm file upload response",
            )
        except MitraSdkError as error:
            # Nothing is deleted: the bytes are in storage and the API may even have confirmed them
            # before the answer was lost, so the caller decides with the file_id.
            raise MitraFileTransferError(
                f"File {file_id} was sent but not confirmed: {error}",
                file_id=file_id,
                step="confirm",
            ) from error

    def delete(self, file_id: str) -> None:
        payload = self._transport.request("DELETE", "data-manager", _file_path(file_id))
        if payload is not None:
            raise MitraResponseError("Delete file response must be empty")

    # The signed link lives only in this frame, which has returned by the time upload raises: an
    # error reporter that captures the locals of each frame (Sentry, pytest --showlocals) would
    # otherwise print it next to a send or confirm failure.
    def _request_and_send(
        self,
        content: bytes,
        request: dict[str, object],
    ) -> tuple[str, StorageResponse]:
        upload = expect_file_upload(
            self._transport.request("POST", "data-manager", "/api/v1/files", json_body=request),
            "File upload response",
        )
        sent = self._transport.storage_request(
            upload["uploadMethod"],
            upload["uploadUrl"],
            headers=upload["uploadHeaders"],
            content=content,
        )
        return upload["fileId"], sent

    def _delete_pending(self, file_id: str) -> bool:
        try:
            self.delete(file_id)
        except MitraSdkError:
            return False
        return True


def _file_path(file_id: str) -> str:
    return f"/api/v1/files/{encode_path_segment(file_id, 'file_id')}"
