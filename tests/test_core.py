"""Focused regression tests for the local orchestration layer."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from chat_monitor import ChatMonitor
from local_audio_server import LocalAudioServer
from steering_server import SteeringServer
from music_generator import MusicGenerator
from stream_controller import StreamController
from vibe_analyzer import VibeAnalyzer


class CoreTests(unittest.TestCase):
    def test_vibe_validation_handles_untrusted_energy(self) -> None:
        vibe = VibeAnalyzer._validate_vibe({"energy": "not-a-number", "tags": "bad"})
        self.assertEqual(vibe["energy"], 3)
        self.assertEqual(vibe["tags"], ["chill"])

    def test_music_generator_public_state_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generator = MusicGenerator(queue_dir=str(root / "queue"), playing_dir=str(root / "playing"),
                                       played_dir=str(root / "played"))
            generator.state_file = str(root / "state.json")
            generator.update_state(songs_generated_increment=2, isActive=True)
            self.assertEqual(generator._update_state.__name__, "_update_state")
            self.assertEqual(__import__("json").loads((root / "state.json").read_text())["songsGenerated"], 2)

    def test_stream_status_does_not_expose_stream_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            controller = StreamController(youtube_stream_key="secret")
            controller.state_file = Path(temporary) / "state.json"
            controller._save_state({"streamKey": "secret"})
            self.assertNotIn("streamKey", controller.get_status())

    def test_next_track_is_oldest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = StreamController(youtube_stream_key="secret")
            controller.queue_dir = root
            older = root / "older.mp3"
            older.write_bytes(b"")
            (root / "newer.mp3").write_bytes(b"")
            os.utime(older, (1, 1))
            self.assertEqual(controller._next_queued_track().name, "older.mp3")

    def test_local_audio_mode_does_not_need_an_rtmp_key(self) -> None:
        controller = StreamController()

        async def discard_audio(data: bytes) -> None:
            return None

        controller.set_audio_sink(discard_audio)
        self.assertIs(controller.audio_sink, discard_audio)

    def test_local_server_defaults_to_lan_binding(self) -> None:
        server = LocalAudioServer()
        self.assertEqual((server.host, server.port), ("0.0.0.0", 8090))

    def test_steering_server_defaults_to_localhost(self) -> None:
        async def callback(payload):
            return payload

        server = SteeringServer(callback)
        self.assertEqual((server.host, server.port, server.token), ("127.0.0.1", 8091, None))

class AsyncCoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_monitor_awaits_async_callback(self) -> None:
        monitor = ChatMonitor(api_key="key", live_chat_id="chat", poll_interval=0)
        seen = []

        async def callback(messages):
            seen.extend(messages)
            raise asyncio.CancelledError

        async def poll_chat():
            return [{"author": "viewer", "text": "jazz", "timestamp": None}]

        monitor.poll_chat = poll_chat  # type: ignore[method-assign]
        with self.assertRaises(asyncio.CancelledError):
            await monitor.run(callback)
        self.assertEqual(seen[0]["text"], "jazz")

    async def test_lan_steering_requires_a_token(self) -> None:
        async def callback(payload):
            return payload

        server = SteeringServer(callback, host="0.0.0.0", port=0)
        with self.assertRaisesRegex(RuntimeError, "STEERING_TOKEN"):
            await server.start()


if __name__ == "__main__":
    unittest.main()
