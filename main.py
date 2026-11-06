"""
Orchestrator Entry Point - Ties all components into a perpetual loop.
Starts YouTube broadcast, pre-generates initial songs, starts FFmpeg streaming,
then runs chat monitor → vibe analyzer → music generator continuously.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Dict, List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
from loguru import logger

logger.add(
    os.path.join(os.path.dirname(__file__), "main.log"),
    rotation="10 MB",
    retention="7 days",
    level=os.getenv("LOG_LEVEL", "INFO")
)


class LiveMusicStream:
    """Orchestrates chat monitoring, vibe analysis, and music generation."""

    DEFAULT_VIBE = {
        "energy": 3,
        "genre": "lofi",
        "tags": ["chill", "lofi hip hop", "relaxed"],
        "vocal_style": "instrumental",
        "direction": "default chill lofi beat",
        "lyrics_language": "en",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        live_chat_id: Optional[str] = None,
        youtube_stream_url: Optional[str] = None,
        youtube_stream_key: Optional[str] = None,
        vibe_analyzer_url: Optional[str] = None,
        ace_step_url: Optional[str] = None,
    ) -> None:
        """
        Initialize the live music stream orchestrator.
        
        Args:
            api_key: YouTube API key (defaults to env var YOUTUBE_API_KEY)
            live_chat_id: Live chat ID (defaults to env var LIVE_CHAT_ID)
            youtube_stream_url: YouTube stream URL (defaults to env var YOUTUBE_STREAM_URL)
            youtube_stream_key: YouTube stream key (defaults to env var YOUTUBE_STREAM_KEY)
            vibe_analyzer_url: Vibe analyzer API URL (defaults to env var VIBE_API_URL)
            ace_step_url: ACE-Step API URL (defaults to env var ACE_STEP_URL)
        """
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        self.live_chat_id = live_chat_id or os.getenv("LIVE_CHAT_ID")
        self.youtube_stream_url = youtube_stream_url or os.getenv("YOUTUBE_STREAM_URL", "rtmp://a.rtmp.youtube.com/live2")
        self.youtube_stream_key = youtube_stream_key or os.getenv("YOUTUBE_STREAM_KEY")
        self.vibe_analyzer_url = vibe_analyzer_url or os.getenv("VIBE_API_URL", "http://localhost:8000")
        self.ace_step_url = ace_step_url or os.getenv("ACE_STEP_URL", "http://127.0.0.1:8002")

        if not self.api_key or not self.live_chat_id:
            logger.warning("Missing YOUTUBE_API_KEY or LIVE_CHAT_ID, using placeholder values")

        from chat_monitor import ChatMonitor
        from vibe_analyzer import VibeAnalyzer
        from music_generator import MusicGenerator
        from stream_controller import StreamController

        self.chat_monitor = ChatMonitor(api_key=self.api_key, live_chat_id=self.live_chat_id)
        self.vibe_analyzer = VibeAnalyzer(api_url=self.vibe_analyzer_url)
        self.music_generator = MusicGenerator(ace_step_url=self.ace_step_url)
        self.stream_controller = StreamController(
            youtube_api_key=self.api_key,
            youtube_stream_url=self.youtube_stream_url,
            youtube_stream_key=self.youtube_stream_key,
            live_chat_id=self.live_chat_id,
        )

        self.current_vibe: Dict = dict(self.DEFAULT_VIBE)
        self.running = False
        self.local_audio_server = None
        self.steering_server = None

    async def _generate_initial_songs(self, count: int = 3) -> None:
        """
        Generate initial songs with default vibe before stream starts.
        
        Args:
            count: Number of initial songs to generate
        """
        logger.info(f"Generating {count} initial songs with default vibe...")
        for i in range(count):
            filename = await self.music_generator.generate_song(self.current_vibe)
            if filename:
                logger.info(f"  [{i+1}/{count}] Generated: {filename}")
            else:
                logger.warning(f"  [{i+1}/{count}] Failed to generate song {i+1}")
            await asyncio.sleep(1)

    async def _apply_vibe(self, vibe: Dict) -> Dict:
        """Persist a vibe and immediately queue a song for it."""
        self.current_vibe = vibe
        mood_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mood.json")
        async with aiofiles.open(mood_file, "w") as f:
            await f.write(json.dumps(vibe, indent=2))
        filename = await self.music_generator.generate_song(vibe)
        if filename:
            logger.info("Queued steered song: {}", filename)
        else:
            logger.warning("Song generation failed after vibe update")
        return {"vibe": vibe, "queuedSong": filename or None}

    async def _on_chat_messages(self, messages: List[Dict]) -> None:
        """
        Callback when new chat messages are received.
        
        Args:
            messages: List of chat message dictionaries
        """
        if not messages or len(messages) == 0:
            return

        logger.info(f"Processing {len(messages)} new chat messages...")

        vibe = await self.vibe_analyzer.analyze(messages)
        logger.info(f"Updated vibe: {vibe}")
        await self._apply_vibe(vibe)

    async def _on_steer(self, request: Dict) -> Dict:
        """Apply a human operator nudge received from the steering endpoint."""
        if request.get("prompt"):
            vibe = await self.vibe_analyzer.analyze([{
                "author": "stream operator", "text": str(request["prompt"]), "timestamp": None,
            }])
        else:
            override = request.get("vibe")
            if not isinstance(override, dict):
                raise ValueError("vibe must be an object")
            merged = dict(self.current_vibe)
            merged.update(override)
            vibe = self.vibe_analyzer._validate_vibe(merged)
        logger.info("Applying manual steering: {}", vibe)
        return await self._apply_vibe(vibe)

    async def run(self) -> None:
        """Main orchestrator loop."""
        logger.info("=" * 60)
        logger.info("  LIVE PERPETUAL GENERATIVE MUSIC AI - STARTING")
        logger.info("=" * 60)

        self.running = True

        # This control endpoint is independent of the selected audio output mode.
        from steering_server import SteeringServer
        self.steering_server = SteeringServer(
            self._on_steer,
            host=os.getenv("STEERING_HOST", "127.0.0.1"),
            port=int(os.getenv("STEERING_PORT", "8091")),
            token=os.getenv("STEERING_TOKEN") or None,
        )
        await self.steering_server.start()

        # Optional local/LAN audio test endpoint.
        if os.getenv("STREAM_OUTPUT", "rtmp").lower() == "local":
            from local_audio_server import LocalAudioServer
            self.local_audio_server = LocalAudioServer(
                host=os.getenv("LOCAL_STREAM_HOST", "0.0.0.0"),
                port=int(os.getenv("LOCAL_STREAM_PORT", "8090")),
            )
            await self.local_audio_server.start()
            self.stream_controller.set_audio_sink(self.local_audio_server.publish)

        # Step 1: Start YouTube broadcast
        logger.info("\n[1/4] Starting YouTube broadcast...")
        if self.local_audio_server is None and not await self.stream_controller.start_broadcast():
            raise RuntimeError("Unable to start the configured YouTube broadcast")

        # Step 2: Generate initial songs with default vibe
        logger.info("\n[2/4] Generating initial songs...")
        await self._generate_initial_songs(count=3)

        # Step 3: Start FFmpeg queue worker
        logger.info("\n[3/4] Starting FFmpeg RTMP stream...")
        queue_task = asyncio.create_task(self.stream_controller.run_queue(), name="ffmpeg-queue")

        # Step 4: Run chat monitor loop
        logger.info("\n[4/4] Starting chat monitoring loop...")
        logger.info("Chat Monitor → Vibe Analyzer → Music Generator loop active.\n")

        chat_task = asyncio.create_task(self.chat_monitor.run(self._on_chat_messages), name="chat-monitor")

        try:
            await chat_task
        except asyncio.CancelledError:
            logger.info("Chat monitoring task cancelled")
        finally:
            chat_task.cancel()
            queue_task.cancel()
            await asyncio.gather(chat_task, queue_task, return_exceptions=True)

    async def stop(self) -> None:
        """Stop all components."""
        self.running = False
        logger.info("\nStopping stream...")

        self.stream_controller.stop_ffmpeg_stream()
        await self.stream_controller.stop_broadcast()
        if self.local_audio_server is not None:
            await self.local_audio_server.stop()
        if self.steering_server is not None:
            await self.steering_server.stop()

        await self.chat_monitor.close()
        await self.vibe_analyzer.close()
        await self.music_generator.close()

        logger.info("All components stopped.")


async def main():
    """
    Entry point - reads env vars for config, creates LiveMusicStream, calls run().
    """
    api_key = os.getenv("YOUTUBE_API_KEY")
    live_chat_id = os.getenv("LIVE_CHAT_ID")
    stream_url = os.getenv("YOUTUBE_STREAM_URL", "rtmp://a.rtmp.youtube.com/live2")
    stream_key = os.getenv("YOUTUBE_STREAM_KEY")

    if not api_key or not live_chat_id:
        logger.warning("YOUTUBE_API_KEY and/or LIVE_CHAT_ID not set in environment.")
        logger.warning("Using placeholder values. Set env vars for full functionality.\n")
        api_key = "demo_api_key"
        live_chat_id = "demo_chat_id"

    stream = LiveMusicStream(
        api_key=api_key,
        live_chat_id=live_chat_id,
        youtube_stream_url=stream_url,
        youtube_stream_key=stream_key,
    )

    try:
        await stream.run()
    except KeyboardInterrupt:
        logger.info("\nKeyboardInterrupt received, shutting down...")
    finally:
        await stream.stop()


if __name__ == "__main__":
    asyncio.run(main())
