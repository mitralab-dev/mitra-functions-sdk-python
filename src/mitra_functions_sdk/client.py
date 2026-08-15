from __future__ import annotations

from collections.abc import Mapping

from ._http import HttpTransport
from ._path import encode_path_segment
from ._response import expect_object
from .auth import AuthModule
from .config import MitraClientConfig
from .entities import EntitiesModule
from .errors import MitraResponseError
from .functions import FunctionsModule
from .integration import IntegrationModule
from .queries import QueriesModule


class MitraClient:
    """Synchronous Mitra client designed for the current Python function runner."""

    def __init__(self, config: MitraClientConfig) -> None:
        self.config = config
        self.data_source_id = config.data_source_id
        self._transport = HttpTransport(config)
        self.auth = AuthModule(self._transport)
        self.entities = EntitiesModule(self._transport)
        self.queries = QueriesModule(self._transport, lambda: self.data_source_id)
        self.functions = FunctionsModule(self._transport)
        self.integration = IntegrationModule(self._transport)

    def init(self) -> None:
        if self.data_source_id is not None:
            return
        app_info = expect_object(
            self._transport.request(
                "GET",
                "code-studio",
                f"/api/v1/apps/{encode_path_segment(self.config.app_id, 'app_id')}/info",
            ),
            "App info response",
        )
        data_source_id = app_info.get("dataSourceId")
        if not isinstance(data_source_id, str) or not data_source_id.strip():
            raise MitraResponseError("App info response must include dataSourceId")
        self.data_source_id = data_source_id

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> MitraClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def create_client(config: MitraClientConfig | None = None) -> MitraClient:
    return MitraClient(config or MitraClientConfig.from_environment())


def create_client_from_environment(env: Mapping[str, str] | None = None) -> MitraClient:
    return MitraClient(MitraClientConfig.from_environment(env))
