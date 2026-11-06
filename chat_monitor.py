"""
YouTube Live Chat Monitor - Polls YouTube Live chat and returns recent messages.
"""

import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Awaitable, List, Dict, Optional, Callable, Union
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
from loguru import logger

logger.add(
    os.path.join(os.path.dirname(__file__), "chat_monitor.log"),
    rotation="10 MB",
    retention="7 days",
    level=os.getenv("LOG_LEVEL", "INFO")
)

# Import retry and rate limiting utilities
from utils import retry, RateLimiter


class ChatMonitor:
    """Polls YouTube Live chat via the YouTube Data API v3."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        live_chat_id: Optional[str] = None,
        poll_interval: int = 45,
        max_results: int = 20,
    ) -> None:
        """
        Initialize the chat monitor.
        
        Args:
            api_key: YouTube API key (defaults to env var YOUTUBE_API_KEY)
            live_chat_id: Live chat ID (defaults to env var LIVE_CHAT_ID)
            poll_interval: Polling interval in seconds (defaults to env var CHAT_POLL_INTERVAL)
            max_results: Maximum messages to fetch per poll (defaults to env var CHAT_MAX_RESULTS)
        """
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        self.live_chat_id = live_chat_id or os.getenv("LIVE_CHAT_ID")
        self.poll_interval = int(os.getenv("CHAT_POLL_INTERVAL", str(poll_interval)))
        self.max_results = int(os.getenv("CHAT_MAX_RESULTS", str(max_results)))
        self.base_url = "https://youtube.googleapis.com/youtube/v3/liveChatMessages"
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limiter = RateLimiter(calls_per_second=2.0)
        self.page_token: Optional[str] = None
        self.seen_message_ids: set[str] = set()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure aiohttp session is available and not closed."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    @retry(max_attempts=3, delay=1.0, backoff=2.0, exceptions=(aiohttp.ClientError, RuntimeError))
    async def poll_chat(self) -> Optional[List[Dict]]:
        """
        Poll YouTube Live chat and return list of message dicts.
        
        Returns:
            List of message dicts or None if error occurs.
            Each dict: {"author": str, "text": str, "timestamp": datetime}
        """
        if not self.api_key or not self.live_chat_id:
            logger.error("Missing API key or live chat ID")
            return None

        params = {
            "part": "snippet",
            "liveChatId": self.live_chat_id,
            "key": self.api_key,
            "maxResults": str(self.max_results),
        }
        if self.page_token:
            params["pageToken"] = self.page_token

        session = await self._ensure_session()
        await self.rate_limiter.acquire()
        try:
            async with session.get(self.base_url, params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"YouTube API returned status {response.status}: {error_text}")
                    return None

                data = await response.json()
                self.page_token = data.get("nextPageToken", self.page_token)

                if "items" not in data or not data["items"]:
                    return []

                messages = []
                for item in data["items"]:
                    message_id = item.get("id")
                    if message_id and message_id in self.seen_message_ids:
                        continue
                    snippet = item.get("snippet", {})
                    message_details = snippet.get("chatMessageDetails", {})

                    # Skip removed messages
                    if message_details.get("chatState") == "removed":
                        continue

                    # Skip super chats
                    if snippet.get("superChatDetails"):
                        continue

                    # Skip member messages
                    if snippet.get("memberDetails"):
                        continue

                    # Skip system messages
                    if snippet.get("systemMessageDetails"):
                        continue

                    text_message = snippet.get("textMessageDetails", {})
                    if not text_message or not text_message.get("messageText"):
                        continue

                    author_display = snippet.get("authorChannel", {}).get(
                        "displayName", "Unknown"
                    )
                    message_text = text_message["messageText"]
                    timestamp_str = snippet.get("publishedAt")

                    if timestamp_str:
                        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    else:
                        timestamp = datetime.now(timezone.utc)

                    messages.append(
                        {
                            "author": author_display,
                            "text": message_text,
                            "timestamp": timestamp,
                        }
                    )
                    if message_id:
                        self.seen_message_ids.add(message_id)

                # Keep deduplication state bounded for a perpetual process.
                if len(self.seen_message_ids) > 2000:
                    self.seen_message_ids = set(list(self.seen_message_ids)[-1000:])

                if messages:
                    logger.info(f"Received {len(messages)} chat messages")
                return messages if messages else None
        except aiohttp.ClientError as e:
            logger.error(f"Chat monitor network error: {e}")
            return None
        except Exception as e:
            logger.error(f"Chat monitor error: {e}")
            return None

    async def run(self, callback: Union[Callable[[List[Dict]], None], Callable[[List[Dict]], Awaitable[None]]]) -> None:
        """
        Async loop calling callback with chat messages every poll_interval seconds.
        
        Args:
            callback: Function to call with list of messages
        """
        logger.info(f"ChatMonitor started - polling chat every {self.poll_interval}s")
        while True:
            try:
                messages = await self.poll_chat()
                if messages and len(messages) > 0:
                    result = callback(messages)
                    if asyncio.iscoroutine(result):
                        await result
                else:
                    logger.debug("No new chat messages")
            except Exception as e:
                logger.error(f"Chat monitor error in loop: {e}")

            await asyncio.sleep(self.poll_interval)

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()


async def main():
    """Test the chat monitor with sample data."""
    api_key = os.getenv("YOUTUBE_API_KEY")
    live_chat_id = os.getenv("LIVE_CHAT_ID")

    if not api_key or not live_chat_id:
        logger.error("Missing API key or live chat ID - set environment variables")
        return

    monitor = ChatMonitor(api_key, live_chat_id)

    def on_chat_messages(messages: List[Dict]) -> None:
        logger.info(f"Received {len(messages)} messages:")
        for msg in messages:
            logger.info(f"  [{msg['author']}]: {msg['text']}")

    await monitor.run(on_chat_messages)


if __name__ == "__main__":
    asyncio.run(main())
