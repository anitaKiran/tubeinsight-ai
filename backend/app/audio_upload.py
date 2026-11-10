"""Bound the entire multipart body before parsing, including chunked uploads."""
import anyio
from starlette.responses import JSONResponse
from app.schemas.error import ApiException
from app.services.audio_service import AudioSettings


class AudioUploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/api/audio/transcribe" or scope.get("method") != "POST":
            return await self.app(scope, receive, send)
        body = bytearray()
        try:
            limit = AudioSettings.from_env().max_bytes + 64_000
            headers = dict(scope.get("headers", []))
            try:
                length = int(headers.get(b"content-length", b"0"))
            except ValueError:
                raise ApiException(400, "AUDIO_INVALID", "Invalid upload content length.") from None
            if length > limit:
                raise ApiException(413, "AUDIO_TOO_LARGE", "The multipart upload exceeds the configured audio limit.")
            with anyio.fail_after(15):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > limit:
                        raise ApiException(413, "AUDIO_TOO_LARGE", "The multipart upload exceeds the configured audio limit.")
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            error = ApiException(408, "AUDIO_UPLOAD_TIMEOUT", "The audio upload timed out.")
        except ApiException as exc:
            error = exc
        else:
            payload = bytes(body)
            body.clear()
            consumed = False
            async def replay():
                nonlocal consumed, payload
                if consumed:
                    return await receive()
                consumed = True
                result = {"type": "http.request", "body": payload, "more_body": False}
                payload = b""
                return result
            try:
                return await self.app(scope, replay, send)
            finally:
                payload = b""
        body.clear()
        await JSONResponse({"error": {"code": error.code, "message": error.message}}, status_code=error.status_code)(scope, receive, send)
