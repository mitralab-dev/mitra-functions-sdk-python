from __future__ import annotations

from collections.abc import Mapping

from ._http import HttpTransport
from ._path import encode_path_segment
from ._response import expect_proxy_result
from .models import ProxyInput, ProxyResult


class IntegrationModule:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def execute_resource(
        self,
        resource_id: str,
        params: Mapping[str, object] | None = None,
    ) -> ProxyResult:
        encoded_resource_id = encode_path_segment(resource_id, "resource_id")
        return expect_proxy_result(
            self._transport.request(
                "POST",
                "integration",
                f"/api/v1/proxy/resources/{encoded_resource_id}/execute",
                json_body={"params": dict(params or {})},
            ),
            "Integration resource response",
        )

    def execute(self, config_id: str, request: ProxyInput) -> ProxyResult:
        body: dict[str, object] = dict(request)
        body["source"] = "SDK"
        encoded_config_id = encode_path_segment(config_id, "config_id")
        return expect_proxy_result(
            self._transport.request(
                "POST",
                "integration",
                f"/api/v1/proxy/template-configs/{encoded_config_id}/execute",
                json_body=body,
            ),
            "Integration proxy response",
        )
