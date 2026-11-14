from typing import NotRequired, TypedDict

Record = dict[str, object]


class Plan(TypedDict):
    id: str
    name: str


class Tenant(TypedDict):
    id: str
    shortId: str
    legacyId: int | None
    slug: str
    plan: Plan
    name: str
    description: str | None
    hexColor: str | None
    icon: str | None
    infraStatus: str
    active: bool


class CurrentUser(TypedDict):
    id: str
    tenant: Tenant
    name: str
    email: str
    imageUrl: str | None
    onboardingCompleted: bool


class QueryResult(TypedDict):
    rows: list[Record]
    affectedRows: NotRequired[int | None]
    durationMs: int


class DeleteManyResult(TypedDict):
    deleted: int


class FunctionExecution(TypedDict):
    id: str
    functionId: str
    functionVersionId: str
    status: str
    input: Record | None
    output: Record | None
    errorMessage: str | None
    logs: str | None
    durationMs: int | None
    startedAt: str | None
    finishedAt: str | None
    createdAt: str


class ProxyInput(TypedDict):
    method: str
    endpoint: str
    headers: NotRequired[dict[str, str]]
    body: NotRequired[object]
    queryParams: NotRequired[dict[str, object]]


class ProxyResult(TypedDict):
    status: int
    headers: dict[str, str]
    body: object
    durationMs: int
    executionId: str


class FileMetadata(TypedDict):
    id: str
    name: str
    contentType: str
    sizeBytes: int
    kind: str
    visibility: str
    status: str
    ownerUserId: str | None
    createdBy: str
    createdAt: str
    confirmedAt: str | None
    expiresAt: str | None


class FileReadUrl(TypedDict):
    url: str
    expiresAt: str


class FileUpload(TypedDict):
    fileId: str
    uploadUrl: str
    uploadMethod: str
    uploadHeaders: dict[str, str]
    expiresAt: str
