"""Small HTTP MP3 broadcaster for local and LAN stream testing."""

import asyncio
from typing import Set

from aiohttp import web
from loguru import logger


class LocalAudioServer:
    """Fan out FFmpeg MP3 bytes to any connected HTTP audio clients."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8090) -> None:
        self.host = host
        self.port = port
        self._clients: Set[asyncio.Queue[bytes]] = set()
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        app = web.Application()
        app.add_routes([web.get("/", self._index), web.get("/stream.mp3", self._stream)])
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("Local audio test stream listening on http://{}:{}/stream.mp3", self.host, self.port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def publish(self, data: bytes) -> None:
        """Send an audio chunk to all current clients without blocking FFmpeg."""
        for client in tuple(self._clients):
            try:
                client.put_nowait(data)
            except asyncio.QueueFull:
                # A slow client must not make the live encoder fall behind.
                try:
                    client.get_nowait()
                    client.put_nowait(data)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def _index(self, request: web.Request) -> web.Response:
        stream_url = f"http://{request.host}/stream.mp3"
        return web.Response(
            text=("<h1>Perpetual Music local stream</h1>"
                  f"<p>Open <a href='{stream_url}'>{stream_url}</a> in VLC, iTunes, or another MP3 client.</p>"),
            content_type="text/html",
        )

    async def _stream(self, request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            status=200,
            headers={"Content-Type": "audio/mpeg", "Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
        await response.prepare(request)
        client: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
        self._clients.add(client)
        logger.info("Local audio client connected ({} total)", len(self._clients))
        try:
            while True:
                await response.write(await client.get())
        except (asyncio.CancelledError, ConnectionResetError, RuntimeError):
            pass
        finally:
            self._clients.discard(client)
            logger.info("Local audio client disconnected ({} total)", len(self._clients))
        return response
