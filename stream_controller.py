"""FFmpeg queue playback and optional YouTube Live broadcast lifecycle management."""

import asyncio
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

import aiohttp
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


class StreamController:
    """Streams queued tracks one at a time and archives tracks after playback.

    FFmpeg reads a concat playlist only once, so it cannot safely discover songs
    created after startup. This controller instead consumes queue/ track by track,
    ensuring new songs are picked up rather than repeating a stale startup list.
    """

    def __init__(self, youtube_api_key: Optional[str] = None,
                 youtube_stream_url: Optional[str] = None,
                 youtube_stream_key: Optional[str] = None,
                 live_chat_id: Optional[str] = None,
                 oauth_access_token: Optional[str] = None) -> None:
        root = Path(__file__).resolve().parent
        self.youtube_api_key = youtube_api_key or os.getenv("YOUTUBE_API_KEY")
        self.youtube_stream_url = youtube_stream_url or os.getenv(
            "YOUTUBE_STREAM_URL", "rtmp://a.rtmp.youtube.com/live2")
        self.youtube_stream_key = youtube_stream_key or os.getenv("YOUTUBE_STREAM_KEY")
        self.live_chat_id = live_chat_id or os.getenv("LIVE_CHAT_ID")
        self.oauth_access_token = oauth_access_token or os.getenv("YOUTUBE_OAUTH_ACCESS_TOKEN")
        self.manage_broadcast = os.getenv("YOUTUBE_MANAGE_BROADCAST", "false").lower() == "true"
        self.state_file = root / "state.json"
        self.queue_dir, self.playing_dir, self.played_dir = root / "queue", root / "playing", root / "played"
        self.ffmpeg_process: Optional[subprocess.Popen[bytes]] = None
        self.broadcast_id: Optional[str] = None
        self.stream_id: Optional[str] = None
        self._stop_requested = False
        self.audio_sink: Optional[Callable[[bytes], Awaitable[None]]] = None
        for directory in (self.queue_dir, self.playing_dir, self.played_dir):
            directory.mkdir(exist_ok=True)

    def _load_state(self) -> Dict[str, Any]:
        try:
            with self.state_file.open(encoding="utf-8") as file:
                return json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """Atomically persist non-secret stream status."""
        state["lastUpdated"] = datetime.now(timezone.utc).isoformat()
        temporary = self.state_file.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=2)
        temporary.replace(self.state_file)

    def _headers(self) -> Dict[str, str]:
        if not self.oauth_access_token:
            raise RuntimeError("YOUTUBE_OAUTH_ACCESS_TOKEN is required to manage broadcasts")
        return {"Authorization": f"Bearer {self.oauth_access_token}"}

    async def start_broadcast(self) -> bool:
        """Create/bind a YouTube broadcast when explicitly enabled with OAuth."""
        if not self.manage_broadcast:
            logger.info("YouTube broadcast management disabled; using configured RTMP target")
            return True
        if not self.youtube_stream_key:
            logger.error("YOUTUBE_STREAM_KEY is required for RTMP streaming")
            return False
        try:
            async with aiohttp.ClientSession(headers=self._headers()) as session:
                broadcast = {"snippet": {"title": "AI Generated Music Stream",
                             "description": "Live perpetual generative AI music stream",
                             "scheduledStartTime": datetime.now(timezone.utc).isoformat()},
                             "status": {"privacyStatus": "unlisted"}}
                async with session.post("https://www.googleapis.com/youtube/v3/liveBroadcasts",
                                        params={"part": "snippet,status"}, json=broadcast) as response:
                    response.raise_for_status()
                    self.broadcast_id = (await response.json())["id"]
                stream = {"snippet": {"title": "AI Music Stream"},
                          "cdn": {"ingestionType": "rtmp", "resolution": "variable", "frameRate": "variable"}}
                async with session.post("https://www.googleapis.com/youtube/v3/liveStreams",
                                        params={"part": "snippet,cdn"}, json=stream) as response:
                    response.raise_for_status()
                    self.stream_id = (await response.json())["id"]
                async with session.post("https://www.googleapis.com/youtube/v3/liveBroadcasts/bind",
                                        params={"part": "id", "id": self.broadcast_id, "streamId": self.stream_id}) as response:
                    response.raise_for_status()
                async with session.post("https://www.googleapis.com/youtube/v3/liveBroadcasts/transition",
                                        params={"part": "id,status", "id": self.broadcast_id,
                                                "broadcastStatus": "testing"}) as response:
                    response.raise_for_status()
        except (aiohttp.ClientError, KeyError, RuntimeError) as error:
            logger.error("Could not start YouTube broadcast: {}", error)
            return False
        state = self._load_state()
        state.update({"broadcastId": self.broadcast_id, "liveChatId": self.live_chat_id, "isActive": True})
        self._save_state(state)
        return True

    async def stop_broadcast(self) -> bool:
        """Transition an application-managed YouTube broadcast to complete."""
        broadcast_id = self.broadcast_id or self._load_state().get("broadcastId")
        if not self.manage_broadcast or not broadcast_id:
            return True
        try:
            async with aiohttp.ClientSession(headers=self._headers()) as session:
                async with session.post("https://www.googleapis.com/youtube/v3/liveBroadcasts/transition",
                                        params={"part": "id,status", "id": broadcast_id,
                                                "broadcastStatus": "complete"}) as response:
                    response.raise_for_status()
        except (aiohttp.ClientError, RuntimeError) as error:
            logger.error("Could not stop YouTube broadcast: {}", error)
            return False
        state = self._load_state()
        state["isActive"] = False
        self._save_state(state)
        return True

    def get_status(self) -> Dict[str, Any]:
        """Return stream state without exposing stream credentials."""
        state = self._load_state()
        return {"broadcastId": state.get("broadcastId"), "liveChatId": state.get("liveChatId"),
                "isActive": state.get("isActive", False),
                "ffmpegRunning": self.ffmpeg_process is not None and self.ffmpeg_process.poll() is None,
                "songsGenerated": state.get("songsGenerated", 0), "songsPlayed": state.get("songsPlayed", 0),
                "lastUpdated": state.get("lastUpdated")}

    def _next_queued_track(self) -> Optional[Path]:
        tracks = sorted(self.queue_dir.glob("*.mp3"), key=lambda path: path.stat().st_mtime)
        return tracks[0] if tracks else None

    def set_audio_sink(self, sink: Optional[Callable[[bytes], Awaitable[None]]]) -> None:
        """Set an async sink for local MP3 broadcasting instead of RTMP output."""
        self.audio_sink = sink

    def start_ffmpeg_stream(self) -> bool:
        """Start FFmpeg for the next queued track and move it into playing/."""
        if self.ffmpeg_process is not None and self.ffmpeg_process.poll() is None:
            return True
        if self.audio_sink is None and not self.youtube_stream_key:
            logger.error("YOUTUBE_STREAM_KEY is required before starting FFmpeg")
            return False
        track = self._next_queued_track()
        if track is None:
            return False
        playing_track = self.playing_dir / track.name
        shutil.move(str(track), str(playing_track))
        command = ["ffmpeg", "-nostdin", "-re", "-i", str(playing_track)]
        if self.audio_sink is None:
            command += ["-c:a", "aac", "-b:a", "192k", "-f", "flv",
                        f"{self.youtube_stream_url.rstrip('/')}/{self.youtube_stream_key}"]
        else:
            command += ["-c:a", "libmp3lame", "-b:a", "192k", "-f", "mp3", "pipe:1"]
        try:
            self.ffmpeg_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE if self.audio_sink else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._current_track = playing_track
            logger.info("Streaming {}", playing_track.name)
            return True
        except (FileNotFoundError, OSError) as error:
            logger.error("Could not start FFmpeg: {}", error)
            shutil.move(str(playing_track), str(self.queue_dir / playing_track.name))
            return False

    async def run_queue(self, poll_interval: float = 1.0) -> None:
        """Continuously play newly queued tracks and archive completed tracks."""
        self._stop_requested = False
        while not self._stop_requested:
            if not self.start_ffmpeg_stream():
                await asyncio.sleep(poll_interval)
                continue
            process = self.ffmpeg_process
            if process is None:
                continue
            relay_task = None
            if self.audio_sink is not None and process.stdout is not None:
                relay_task = asyncio.create_task(self._relay_audio(process), name="local-audio-relay")
            return_code = await asyncio.to_thread(process.wait)
            if relay_task is not None:
                await relay_task
            self.ffmpeg_process = None
            current = getattr(self, "_current_track", None)
            if current and current.exists() and not self._stop_requested:
                shutil.move(str(current), str(self.played_dir / current.name))
                state = self._load_state()
                state["songsPlayed"] = state.get("songsPlayed", 0) + 1
                self._save_state(state)
                if return_code != 0:
                    logger.warning("FFmpeg exited with code {} for {}", return_code, current.name)

    async def _relay_audio(self, process: subprocess.Popen[bytes]) -> None:
        """Read FFmpeg's MP3 pipe continually so it cannot block on a full buffer."""
        if process.stdout is None or self.audio_sink is None:
            return
        while True:
            chunk = await asyncio.to_thread(process.stdout.read, 64 * 1024)
            if not chunk:
                return
            await self.audio_sink(chunk)

    def stop_ffmpeg_stream(self) -> bool:
        self._stop_requested = True
        if self.ffmpeg_process is None or self.ffmpeg_process.poll() is not None:
            return True
        self.ffmpeg_process.terminate()
        try:
            self.ffmpeg_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.ffmpeg_process.kill()
        return True

    async def close(self) -> None:
        self.stop_ffmpeg_stream()
