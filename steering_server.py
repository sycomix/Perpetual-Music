"""Authenticated HTTP control endpoint for manually steering the next song."""

from typing import Any, Awaitable, Callable, Dict, Optional

from aiohttp import web
from loguru import logger


SteerCallback = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


class SteeringServer:
    """Expose an output-independent local control API for stream operators."""

    def __init__(self, callback: SteerCallback, host: str = "127.0.0.1", port: int = 8091,
                 token: Optional[str] = None) -> None:
        self.callback = callback
        self.host = host
        self.port = port
        self.token = token
        self._runner: Optional[web.AppRunner] = None

    async def start(self) -> None:
        if self.host not in {"127.0.0.1", "localhost", "::1"} and not self.token:
            raise RuntimeError("STEERING_TOKEN is required when steering is exposed beyond localhost")
        app = web.Application(client_max_size=16 * 1024)
        app.add_routes([web.get("/", self._index), web.get("/health", self._health),
                        web.post("/steer", self._steer)])
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.host, self.port).start()
        logger.info("Steering control listening on http://{}:{}/steer", self.host, self.port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    def _authorized(self, request: web.Request) -> bool:
        return not self.token or request.headers.get("X-Steer-Token") == self.token

    async def _index(self, request: web.Request) -> web.Response:
        return web.Response(
            text=("POST JSON to /steer. Use {\"prompt\": \"more upbeat jazz\"} "
                  "or {\"vibe\": {\"genre\": \"jazz\", \"energy\": 7}}."),
            content_type="text/plain",
        )

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def _steer(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            raise web.HTTPUnauthorized(text="Invalid or missing X-Steer-Token")
        try:
            payload = await request.json()
        except (ValueError, web.HTTPException):
            raise web.HTTPBadRequest(text="Body must be JSON")
        if not isinstance(payload, dict) or not (payload.get("prompt") or payload.get("vibe")):
            raise web.HTTPBadRequest(text="Provide a non-empty 'prompt' or a 'vibe' object")
        try:
            result = await self.callback(payload)
        except Exception as error:
            logger.exception("Manual steering failed: {}", error)
            raise web.HTTPInternalServerError(text="Could not apply steering request")
        return web.json_response(result)
