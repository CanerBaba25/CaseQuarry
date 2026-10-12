"""Bound request streams before JSON decoding or multipart spool growth."""

import re

from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException

IMPORT_ROUTE = re.compile(r"/api/v1/cases/([A-Za-z0-9_-]{1,64})/imports$")
PART_ROUTE = re.compile(r"/api/v1/cases/[A-Za-z0-9_-]{1,64}/upload-sessions/[A-Za-z0-9_-]{1,64}/parts/\d+$")


def body_limit(settings, scope):
    path, method = scope.get("path", ""), scope.get("method", "")
    if method == "POST" and IMPORT_ROUTE.fullmatch(path):
        return (
            min(settings.max_case_bytes, settings.max_upload_bytes * settings.max_batch_files) + 1024 * 1024
        )
    if method == "PUT" and PART_ROUTE.fullmatch(path):
        return min(settings.max_upload_bytes, 8 * 1024 * 1024)
    return 4 * 1024 * 1024


class RequestSizeLimit:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        maximum, received = body_limit(self.settings, scope), 0
        multipart = any(
            key.lower() == b"content-type" and value.lower().startswith(b"multipart/form-data")
            for key, value in scope.get("headers", ())
        )

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > maximum:
                    scope.setdefault("state", {})["body_limit_exceeded"] = True
                    if multipart:
                        # Starlette closes partial temporary uploads on this exception.
                        raise MultiPartException("The request exceeds its configured limit.")
                    raise HTTPException(
                        413,
                        {
                            "error_code": "REQUEST_TOO_LARGE",
                            "message": "The request exceeds its configured limit.",
                            "retryable": False,
                        },
                    )
            return message

        await self.app(scope, bounded_receive, send)
