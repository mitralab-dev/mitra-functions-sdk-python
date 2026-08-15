from __future__ import annotations

import builtins
import json
from collections.abc import Mapping, Sequence

from ._http import HttpTransport, QueryParam
from ._path import encode_path_segment
from ._response import expect_object, expect_object_list
from .errors import MitraResponseError
from .models import DeleteManyResult, Record


class EntityTable:
    def __init__(self, transport: HttpTransport, table_name: str) -> None:
        self._transport = transport
        self._base_path = f"/api/v1/tables/{encode_path_segment(table_name, 'table_name')}/records"

    def list(
        self,
        *,
        sort: str | None = None,
        limit: int | None = None,
        skip: int | None = None,
        fields: Sequence[str] | None = None,
    ) -> builtins.list[Record]:
        return self._list_records(sort=sort, limit=limit, skip=skip, fields=fields)

    def filter(
        self,
        query: Mapping[str, object],
        *,
        sort: str | None = None,
        limit: int | None = None,
        skip: int | None = None,
        fields: Sequence[str] | None = None,
    ) -> builtins.list[Record]:
        if not isinstance(query, Mapping):
            raise ValueError("query must be a mapping")
        return self._list_records(
            query=query,
            sort=sort,
            limit=limit,
            skip=skip,
            fields=fields,
        )

    def get(self, record_id: str | int) -> Record:
        return expect_object(
            self._transport.request(
                "GET",
                "data-manager",
                f"{self._base_path}/{encode_path_segment(record_id, 'record_id')}",
            ),
            "Entity response",
        )

    def create(self, data: Mapping[str, object]) -> Record:
        return expect_object(
            self._transport.request("POST", "data-manager", self._base_path, json_body=dict(data)),
            "Created entity response",
        )

    def bulk_create(self, records: Sequence[Mapping[str, object]]) -> builtins.list[Record]:
        return expect_object_list(
            self._transport.request(
                "POST",
                "data-manager",
                f"{self._base_path}/bulk",
                json_body=[dict(record) for record in records],
            ),
            "Bulk create response",
        )

    def update(self, record_id: str | int, data: Mapping[str, object]) -> Record:
        return expect_object(
            self._transport.request(
                "PUT",
                "data-manager",
                f"{self._base_path}/{encode_path_segment(record_id, 'record_id')}",
                json_body=dict(data),
            ),
            "Updated entity response",
        )

    def delete(self, record_id: str | int) -> None:
        payload = self._transport.request(
            "DELETE",
            "data-manager",
            f"{self._base_path}/{encode_path_segment(record_id, 'record_id')}",
        )
        if payload is not None:
            raise MitraResponseError("Delete entity response must be empty")

    def delete_many(self, query: Mapping[str, object]) -> DeleteManyResult:
        if not query:
            raise ValueError("query must not be empty for delete_many")
        payload = expect_object(
            self._transport.request(
                "DELETE",
                "data-manager",
                self._base_path,
                params={"q": json.dumps(dict(query), separators=(",", ":"))},
            ),
            "Delete many response",
        )
        deleted = payload.get("deleted")
        if not isinstance(deleted, int) or isinstance(deleted, bool):
            raise MitraResponseError("Delete many response must include an integer deleted count")
        return {"deleted": deleted}

    def _list_records(
        self,
        *,
        query: Mapping[str, object] | None = None,
        sort: str | None = None,
        limit: int | None = None,
        skip: int | None = None,
        fields: Sequence[str] | None = None,
    ) -> builtins.list[Record]:
        params: dict[str, QueryParam] = {}
        if query is not None:
            params["q"] = json.dumps(dict(query), separators=(",", ":"))
        if sort is not None:
            params["sort"] = sort
        if limit is not None:
            params["limit"] = limit
        if skip is not None:
            params["skip"] = skip
        if fields is not None:
            params["fields"] = ",".join(fields)

        payload = expect_object(
            self._transport.request("GET", "data-manager", self._base_path, params=params),
            "Entity list response",
        )
        return expect_object_list(payload.get("data"), "Entity list data")


class EntitiesModule:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport
        self._tables: dict[str, EntityTable] = {}

    def table(self, name: str) -> EntityTable:
        if not name.strip():
            raise ValueError("table_name must not be blank")
        table = self._tables.get(name)
        if table is None:
            table = EntityTable(self._transport, name)
            self._tables[name] = table
        return table
