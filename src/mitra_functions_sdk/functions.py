from __future__ import annotations

from collections.abc import Mapping

from ._http import HttpTransport
from ._path import encode_path_segment
from ._response import expect_function_execution
from .errors import MitraResponseError
from .models import FunctionExecution


class FunctionsModule:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def execute(
        self,
        function_id: str,
        input: Mapping[str, object] | None = None,
    ) -> FunctionExecution:
        return self._execute(function_id, input, invocation_type="sync")

    def execute_async(
        self,
        function_id: str,
        input: Mapping[str, object] | None = None,
    ) -> FunctionExecution:
        return self._execute(function_id, input, invocation_type="async")

    def get_execution(self, execution_id: str) -> FunctionExecution:
        return expect_function_execution(
            self._transport.request(
                "GET",
                "functions",
                f"/api/v1/executions/{encode_path_segment(execution_id, 'execution_id')}",
            ),
            "Function execution response",
        )

    def cancel_execution(self, execution_id: str) -> None:
        payload = self._transport.request(
            "POST",
            "functions",
            f"/api/v1/executions/{encode_path_segment(execution_id, 'execution_id')}/cancel",
        )
        if payload is not None:
            raise MitraResponseError("Cancel execution response must be empty")

    def _execute(
        self,
        function_id: str,
        input: Mapping[str, object] | None,
        *,
        invocation_type: str,
    ) -> FunctionExecution:
        return expect_function_execution(
            self._transport.request(
                "POST",
                "functions",
                f"/api/v1/functions/{encode_path_segment(function_id, 'function_id')}/execute",
                json_body={"input": dict(input or {})},
                headers={"X-Invocation-Type": invocation_type},
            ),
            "Function execution response",
        )
