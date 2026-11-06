"""
Vibe Analyzer - Sends chat messages to OpenAI-compatible API and parses JSON response.
"""

import json
import aiohttp
from typing import List, Dict, Optional
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
from loguru import logger

logger.add(
    os.path.join(os.path.dirname(__file__), "vibe_analyzer.log"),
    rotation="10 MB",
    retention="7 days",
    level=os.getenv("LOG_LEVEL", "INFO")
)

# Import retry and rate limiting utilities
from utils import retry, RateLimiter


class VibeAnalyzer:
    """Analyzes chat messages using an OpenAI-compatible LLM API."""

    ANALYSIS_PROMPT = (
        'You are a "Vibe Curator" for a live AI music stream on YouTube.\n'
        'Viewers are chatting in real-time, and their collective mood determines the next song.\n\n'
        'Analyze these recent chat messages and determine:\n'
        '1. The overall emotional tone (energy level 0-10)\n'
        '2. Preferred genre(s) — pick ONE primary genre\n'
        '3. Preferred mood/atmosphere (descriptive tags)\n'
        '4. Whether vocals should be present or instrumental\n'
        '5. A short creative direction summary (max 80 characters)\n\n'
        'Chat messages:\n{chat_messages}\n\n'
        'Output ONLY valid JSON with this exact structure:\n'
        '{{\n'
        '    "energy": <integer 0-10>,\n'
        '    "genre": "<single genre name>",\n'
        '    "tags": ["tag1", "tag2", "tag3"],\n'
        '    "vocal_style": "<description or \'instrumental\'>",\n'
        '    "direction": "<short creative summary>",\n'
        '    "lyrics_language": "en"\n'
        '}}\n\n'
        'Rules:\n'
        '- If chat is split, pick the dominant direction\n'
        '- If no music preference, default to chill lofi/ambient\n'
        '- Energy 0 = very slow/calm, 10 = very fast/intense\n'
        '- Genre must be a single clear word (e.g., "jazz", "electronic")\n'
        '- Tags should describe instrumentation and atmosphere\n'
        '- If chat mentions lyrics in another language, set lyrics_language accordingly\n'
        '- Handle emojis and slang gracefully\n'
        '- If chat is empty or contains only system messages, return default vibe\n'
        '- If chat contains mixed languages, prioritize the dominant language\n'
        '- If chat is in a language other than English, set lyrics_language accordingly'
    )

    def __init__(
        self,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """
        Initialize the vibe analyzer.
        
        Args:
            api_url: OpenAI-compatible API URL (defaults to env var VIBE_API_URL)
            model: Model name (defaults to env var VIBE_API_MODEL)
        """
        self.api_url = api_url or os.getenv("VIBE_API_URL", "http://localhost:8000")
        self.model = model or os.getenv("VIBE_API_MODEL", "unsloth-mistral")
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limiter = RateLimiter(calls_per_second=2.0)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure aiohttp session is available and not closed."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    @staticmethod
    def _default_vibe() -> Dict:
        """Return safe default vibe."""
        return {
            "energy": 3,
            "genre": "lofi",
            "tags": ["chill", "lofi hip hop", "relaxed"],
            "vocal_style": "instrumental",
            "direction": "default chill lofi beat",
            "lyrics_language": "en",
        }

    @staticmethod
    def _validate_vibe(vibe: Dict) -> Dict:
        """
        Validate and clamp vibe dict to ensure all required keys with correct types.
        
        Args:
            vibe: Vibe dictionary to validate
            
        Returns:
            Validated and clamped vibe dictionary
        """
        if not isinstance(vibe, dict):
            return VibeAnalyzer._default_vibe()
        validated = {}
        try:
            energy = int(vibe.get("energy", 3))
        except (TypeError, ValueError):
            energy = 3
        validated["energy"] = max(0, min(10, energy))
        validated["genre"] = str(vibe.get("genre", "lofi"))
        tags = vibe.get("tags", ["chill"])
        if not isinstance(tags, list) or len(tags) == 0:
            tags = ["chill"]
        validated["tags"] = [str(t) for t in tags[:3]]
        validated["vocal_style"] = str(vibe.get("vocal_style", "instrumental"))
        validated["direction"] = str(vibe.get("direction", ""))[:80]
        validated["lyrics_language"] = str(vibe.get("lyrics_language", "en"))
        return validated

    @retry(max_attempts=3, delay=1.0, backoff=2.0, exceptions=(aiohttp.ClientError, RuntimeError))
    async def analyze(self, chat_messages: List[Dict]) -> Dict:
        """
        Send chat messages to OpenAI-compatible API and parse response.
        
        Args:
            chat_messages: List of chat message dictionaries
            
        Returns:
            Vibe dictionary with validated and clamped values
        """
        if not chat_messages:
            logger.info("No chat messages provided, returning default vibe")
            return self._default_vibe()

        chat_text = "\n".join(
            f"[{msg.get('author', 'Unknown')}] ({msg.get('timestamp', '')}): {msg.get('text', '')}"
            for msg in chat_messages
        )

        prompt = self.ANALYSIS_PROMPT.format(chat_messages=chat_text)

        session = await self._ensure_session()
        await self.rate_limiter.acquire()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 300,
        }

        try:
            async with session.post(
                f"{self.api_url}/v1/chat/completions",
                json=payload,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Vibe analyzer API error ({response.status}): {error_text}")
                    return self._default_vibe()

                data = await response.json()
                choices = data.get("choices", [])
                if not choices:
                    logger.warning("VibeAnalyzer: No choices in API response")
                    return self._default_vibe()

                content = choices[0]["message"]["content"]
                try:
                    vibe = json.loads(content)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.error(f"VibeAnalyzer: Failed to parse JSON from LLM: {e}")
                    vibe = self._default_vibe()

                return self._validate_vibe(vibe)

        except aiohttp.ClientError as e:
            logger.error(f"Vibe analyzer network error: {e}")
            return self._default_vibe()
        except Exception as e:
            logger.error(f"Vibe analyzer error: {e}")
            return self._default_vibe()

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()


async def main():
    """Test the vibe analyzer with sample chat messages."""
    api_url = os.getenv("VIBE_API_URL", "http://localhost:8000")

    analyzer = VibeAnalyzer(api_url=api_url)

    sample_messages = [
        {"author": "User1", "text": "play some jazz!", "timestamp": None},
        {"author": "User2", "text": "more bass!!", "timestamp": None},
    ]

    vibe = await analyzer.analyze(sample_messages)
    logger.info(f"Analyzed vibe: {vibe}")


if __name__ == "__main__":
    asyncio.run(main())
