from __future__ import annotations

from ._http import HttpTransport
from ._response import expect_current_user
from .models import CurrentUser


class AuthModule:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def me(self) -> CurrentUser:
        return expect_current_user(
            self._transport.request("GET", "iam", "/api/v1/auth/me"),
            "Current user response",
        )
