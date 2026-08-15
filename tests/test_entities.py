import json

import httpx
import pytest

from mitra_functions_sdk import MitraClient, MitraClientConfig, MitraResponseError, create_client


def make_client(handler: httpx.MockTransport) -> tuple[MitraClient, httpx.Client]:
    http_client = httpx.Client(transport=handler)
    client = create_client(
        MitraClientConfig(
            api_url="https://api.mitra.test",
            access_token="token",
            app_id="app-1",
            http_client=http_client,
        )
    )
    return client, http_client


def test_list_and_filter_use_current_cloud_path_and_query_options() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "1", "status": "active"}]})

    client, http_client = make_client(httpx.MockTransport(handler))
    tasks = client.entities.table("Sales / 2026")

    assert tasks.list(sort="-created_at", limit=10, skip=20, fields=["id", "status"]) == [
        {"id": "1", "status": "active"}
    ]
    assert tasks.filter({"status": "active", "score": {"$gt": 10}}, limit=5) == [
        {"id": "1", "status": "active"}
    ]

    assert requests[0].url.raw_path.split(b"?", 1)[0] == (
        b"/data-manager/api/v1/tables/Sales%20%2F%202026/records"
    )
    assert dict(requests[0].url.params) == {
        "sort": "-created_at",
        "limit": "10",
        "skip": "20",
        "fields": "id,status",
    }
    assert json.loads(requests[1].url.params["q"]) == {
        "status": "active",
        "score": {"$gt": 10},
    }
    assert requests[1].url.params["limit"] == "5"
    http_client.close()


def test_get_create_bulk_update_delete_and_delete_many() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "DELETE" and request.url.params:
            return httpx.Response(200, json={"deleted": 2})
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.url.path.endswith("/bulk"):
            return httpx.Response(201, json=[{"id": "1"}, {"id": "2"}])
        return httpx.Response(200, json={"id": "record/1", "name": "Task"})

    client, http_client = make_client(httpx.MockTransport(handler))
    tasks = client.entities.table("Task")

    assert tasks.get("record/1")["id"] == "record/1"
    assert tasks.create({"name": "Task"})["name"] == "Task"
    assert tasks.bulk_create([{"name": "A"}, {"name": "B"}]) == [
        {"id": "1"},
        {"id": "2"},
    ]
    assert tasks.update("record/1", {"name": "Updated"})["id"] == "record/1"
    assert tasks.delete("record/1") is None
    assert tasks.delete_many({"status": "done"}) == {"deleted": 2}

    assert requests[0].url.raw_path.endswith(b"/records/record%2F1")
    assert json.loads(requests[1].content) == {"name": "Task"}
    assert json.loads(requests[2].content) == [{"name": "A"}, {"name": "B"}]
    assert requests[3].method == "PUT"
    assert json.loads(requests[3].content) == {"name": "Updated"}
    assert requests[4].method == "DELETE"
    assert json.loads(requests[5].url.params["q"]) == {"status": "done"}
    http_client.close()


def test_table_instances_are_cached_and_names_must_not_be_blank() -> None:
    client, http_client = make_client(
        httpx.MockTransport(lambda _request: httpx.Response(200, json={"data": []}))
    )

    assert client.entities.table("Task") is client.entities.table("Task")
    assert client.entities.table("Task") is not client.entities.table(" Task ")
    with pytest.raises(ValueError, match="table_name"):
        client.entities.table(" ")
    http_client.close()


def test_delete_many_rejects_empty_query_before_request() -> None:
    def unexpected(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("delete_many must validate locally")

    client, http_client = make_client(httpx.MockTransport(unexpected))

    with pytest.raises(ValueError, match="must not be empty"):
        client.entities.table("Task").delete_many({})
    http_client.close()


@pytest.mark.parametrize(
    ("response", "operation", "message"),
    [
        ({"data": ["not-an-object"]}, "list", "array of objects"),
        ({"deleted": True}, "delete_many", "integer deleted count"),
    ],
)
def test_entity_response_validation(
    response: object,
    operation: str,
    message: str,
) -> None:
    client, http_client = make_client(
        httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    )
    table = client.entities.table("Task")

    with pytest.raises(MitraResponseError, match=message):
        if operation == "list":
            table.list()
        else:
            table.delete_many({"id": "1"})
    http_client.close()
