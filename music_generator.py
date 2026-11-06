"""
Music Generator - Sends vibe to ACE-Step API and saves generated MP3 to queue/.
"""

import asyncio
import base64
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import aiohttp
import aiofiles
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
from loguru import logger

logger.add(
    os.path.join(os.path.dirname(__file__), "music_generator.log"),
    rotation="10 MB",
    retention="7 days",
    level=os.getenv("LOG_LEVEL", "INFO")
)

# Import retry and rate limiting utilities
from utils import retry, RateLimiter


class MusicGenerator:
    """Generates music using ACE-Step OpenRouter-compatible API."""

    def __init__(
        self,
        ace_step_url: Optional[str] = None,
        queue_dir: Optional[str] = None,
        playing_dir: Optional[str] = None,
        played_dir: Optional[str] = None,
    ) -> None:
        """
        Initialize the music generator.
        
        Args:
            ace_step_url: ACE-Step API URL (defaults to env var ACE_STEP_URL)
            queue_dir: Queue directory path (defaults to ./queue)
            playing_dir: Playing directory path (defaults to ./playing)
            played_dir: Played directory path (defaults to ./played)
        """
        self.ace_step_url = ace_step_url or os.getenv("ACE_STEP_URL", "http://127.0.0.1:8002")
        self.queue_dir = queue_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue")
        self.playing_dir = playing_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "playing")
        self.played_dir = played_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "played")
        self.state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
        self.session = None
        self.rate_limiter = RateLimiter(calls_per_second=2.0)
        self.duration = float(os.getenv("DEFAULT_DURATION", "30"))

        # Create directories if they don't exist
        os.makedirs(self.queue_dir, exist_ok=True)
        os.makedirs(self.playing_dir, exist_ok=True)
        os.makedirs(self.played_dir, exist_ok=True)

    async def _ensure_session(self):
        """Ensure aiohttp session is available and not closed."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _build_prompt(self, vibe: Dict) -> str:
        """
        Build ACE-Step prompt from vibe dict.
        
        Args:
            vibe: Vibe dictionary
            
        Returns:
            Prompt string for ACE-Step
        """
        energy = vibe.get("energy", 3)
        genre = vibe.get("genre", "lofi")
        tags = vibe.get("tags", ["chill", "lofi hip hop"])
        vocal_style = vibe.get("vocal_style", "instrumental")
        direction = vibe.get("direction", "default chill lofi beat")

        if vocal_style == "instrumental":
            tag0 = tags[0] if len(tags) > 0 else "chill"
            tag1 = tags[1] if len(tags) > 1 else "lofi hip hop"
            content = f"<prompt>Upbeat {genre} track, {tag0}, {tag1}, energy level {energy}/10</prompt>"
        else:
            tag0 = tags[0] if len(tags) > 0 else "catchy"
            content = (
                f"<prompt>{vocal_style} vocals in {genre} style, {tag0}</prompt>\n"
                f"<lyrics>[Verse]\n{direction}[/Verse]"
            )

        return content

    @retry(max_attempts=3, delay=1.0, backoff=2.0, exceptions=(aiohttp.ClientError, RuntimeError))
    async def generate_song(self, vibe: Dict) -> str:
        """
        Generate a song via ACE-Step API and save to queue/.
        
        Args:
            vibe: Vibe dictionary
            
        Returns:
            Filename of generated song or empty string on failure
        """
        session = await self._ensure_session()
        await self.rate_limiter.acquire()

        lyrics_language = vibe.get("lyrics_language", "en")
        instrumental = vibe.get("vocal_style", "instrumental") == "instrumental"

        prompt_content = self._build_prompt(vibe)

        payload = {
            "messages": [{"role": "user", "content": prompt_content}],
            "audio_config": {
                "duration": self.duration,
                "instrumental": instrumental,
                "vocal_language": lyrics_language,
            },
            "sample_mode": True,
            "use_cot_caption": True,
        }

        try:
            async with session.post(
                f"{self.ace_step_url}/v1/chat/completions",
                json=payload,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"ACE-Step API error {response.status}: {error_text}")
                    return ""

                data = await response.json()
                choices = data.get("choices", [])
                if not choices:
                    logger.error("No choices in ACE-Step response")
                    return ""

                audio_data = choices[0]["message"]["audio"]
                if isinstance(audio_data, list) and len(audio_data) > 0:
                    base64_str = audio_data[0].get("audio_url", {}).get("url", "")
                else:
                    base64_str = audio_data

                if not base64_str:
                    logger.error("No audio data in response")
                    return ""

                if base64_str.startswith("data:"):
                    base64_str = base64_str.split(",", 1)[-1]
                mp3_bytes = base64.b64decode(base64_str, validate=True)

                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                filename = f"song_{timestamp}.mp3"
                filepath = os.path.join(self.queue_dir, filename)

                # Use async file write
                async with aiofiles.open(filepath, "wb") as f:
                    await f.write(mp3_bytes)

                logger.info(f"Generated song: {filename}")
                self.update_state(songs_generated_increment=1)

                return filename

        except aiohttp.ClientError as e:
            logger.error(f"Music generator network error: {e}")
            return ""
        except Exception as e:
            logger.error(f"Music generator error: {e}")
            return ""

    def update_state(self, **kwargs: Any) -> None:
        """
        Update state.json with current stats using atomic write.
        
        Args:
            **kwargs: State fields to update. ``songs_generated_increment`` adds
                to the existing counter rather than replacing it.
        """
        state = {}
        if os.path.exists(self.state_file):
            with open(self.state_file, "r") as f:
                state = json.load(f)
        else:
            state = {
                "broadcastId": None,
                "streamKey": None,
                "liveChatId": None,
                "isActive": False,
                "songsGenerated": 0,
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
            }

        increment = int(kwargs.pop("songs_generated_increment", 0))
        state["songsGenerated"] = state.get("songsGenerated", 0) + increment
        state.update(kwargs)
        state["lastUpdated"] = datetime.now(timezone.utc).isoformat()

        # Atomic write
        temp_file = f"{self.state_file}.tmp"
        with open(temp_file, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(temp_file, self.state_file)

    def _update_state(self, songs_generated_increment: int = 0) -> None:
        """Backward-compatible alias for older callers."""
        self.update_state(songs_generated_increment=songs_generated_increment)

    async def run_generation_loop(self, vibe: Dict, interval: Optional[float] = None) -> None:
        """
        Async loop generating songs based on vibe.
        
        Args:
            vibe: Vibe dictionary
            interval: Generation interval in seconds
        """
        interval = interval if interval is not None else float(os.getenv("GENERATION_INTERVAL", "5"))
        logger.info(f"MusicGenerator started - generating every {interval}s")
        while True:
            filename = await self.generate_song(vibe)
            if filename:
                logger.info(f"Generated song: {filename}")
            else:
                logger.warning("Song generation failed, retrying...")
            await asyncio.sleep(interval)

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()


async def main():
    """Test the music generator."""
    generator = MusicGenerator(ace_step_url="http://127.0.0.1:8002")

    test_vibe = {
        "energy": 7,
        "genre": "jazz",
        "tags": ["smooth saxophone", "swing"],
        "vocal_style": "instrumental",
        "direction": "smooth jazz saxophone solo",
        "lyrics_language": "en",
    }

    result = await generator.generate_song(test_vibe)
    logger.info(f"Generated: {result}")


if __name__ == "__main__":
    asyncio.run(main())
