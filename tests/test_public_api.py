import mitra_functions_sdk
from mitra_functions_sdk import (
    CurrentUser,
    FileMetadata,
    FileReadUrl,
    FunctionExecution,
    Plan,
    QueryResult,
    Tenant,
)


def test_public_api_excludes_internal_module_classes() -> None:
    assert "EntitiesModule" not in mitra_functions_sdk.__all__
    assert "EntityTable" not in mitra_functions_sdk.__all__
    assert not hasattr(mitra_functions_sdk, "EntitiesModule")
    assert not hasattr(mitra_functions_sdk, "EntityTable")
    assert "FilesModule" not in mitra_functions_sdk.__all__
    assert not hasattr(mitra_functions_sdk, "FilesModule")


def test_public_typed_dicts_match_runtime_response_contracts() -> None:
    assert Tenant.__required_keys__ == {
        "id",
        "shortId",
        "legacyId",
        "slug",
        "plan",
        "name",
        "description",
        "hexColor",
        "icon",
        "infraStatus",
        "active",
    }
    assert Tenant.__annotations__["plan"] is Plan
    assert CurrentUser.__annotations__["name"] is str
    assert QueryResult.__optional_keys__ == {"affectedRows"}
    assert FunctionExecution.__annotations__["input"] == dict[str, object] | None
    assert FileMetadata.__required_keys__ == {
        "id",
        "name",
        "contentType",
        "sizeBytes",
        "kind",
        "visibility",
        "status",
        "ownerUserId",
        "createdBy",
        "createdAt",
        "confirmedAt",
        "expiresAt",
    }
    assert FileMetadata.__annotations__["ownerUserId"] == str | None
    assert FileReadUrl.__required_keys__ == {"url", "expiresAt"}
