from __future__ import annotations

from collections.abc import Callable, Mapping

from ._http import HttpTransport
from ._path import encode_path_segment
from ._response import expect_query_result
from .errors import MitraConfigError
from .models import QueryResult


class QueriesModule:
    def __init__(
        self,
        transport: HttpTransport,
        data_source_id: Callable[[], str | None],
    ) -> None:
        self._transport = transport
        self._data_source_id = data_source_id

    def execute(
        self,
        query_id: str,
        parameters: Mapping[str, object] | None = None,
    ) -> QueryResult:
        data_source_id = self._data_source_id()
        if data_source_id is None:
            raise MitraConfigError(
                "data_source_id is unavailable; provide it in configuration or call client.init()"
            )
        return expect_query_result(
            self._transport.request(
                "POST",
                "data-manager",
                f"/api/v1/custom-queries/{encode_path_segment(query_id, 'query_id')}/execute",
                json_body={
                    "dataSourceId": data_source_id,
                    "parameters": dict(parameters or {}),
                },
            ),
            "Query execution response",
        )
