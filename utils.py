"""
Utility functions for rate limiting, retry logic, and common helpers.
"""

import asyncio
import time
from typing import Callable, TypeVar, Optional, Any
from functools import wraps
from loguru import logger

T = TypeVar('T')


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """
    Decorator for retrying a function with exponential backoff.
    
    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff: Multiplier for delay between retries
        exceptions: Tuple of exceptions to catch and retry on
    
    Returns:
        Decorated function with retry logic
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        wait_time = delay * (backoff ** (attempt - 1))
                        logger.warning(
                            f"Attempt {attempt}/{max_attempts} failed for {func.__name__}: {e}. "
                            f"Retrying in {wait_time:.1f}s..."
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"All {max_attempts} attempts failed for {func.__name__}")
            
            raise last_exception
        
        return wrapper
    return decorator


def rate_limit(
    calls_per_second: float = 1.0,
) -> Callable:
    """
    Decorator for rate limiting function calls.
    
    Args:
        calls_per_second: Maximum number of calls per second
    
    Returns:
        Decorated function with rate limiting
    """
    async def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            await asyncio.sleep(1.0 / calls_per_second)
            return await func(*args, **kwargs)
        return wrapper
    return decorator


class RateLimiter:
    """Rate limiter for API calls."""
    
    def __init__(self, calls_per_second: float = 1.0) -> None:
        """
        Initialize the rate limiter.
        
        Args:
            calls_per_second: Maximum number of calls per second
        """
        self.calls_per_second = calls_per_second
        self.last_call_time = 0.0
        self.lock = asyncio.Lock()
    
    async def acquire(self) -> None:
        """Acquire rate limit by waiting if necessary."""
        async with self.lock:
            current_time = time.time()
            time_since_last_call = current_time - self.last_call_time
            
            if time_since_last_call < 1.0 / self.calls_per_second:
                wait_time = (1.0 / self.calls_per_second) - time_since_last_call
                await asyncio.sleep(wait_time)
            
            self.last_call_time = time.time()
    
    async def __call__(self, func: Callable[..., T]) -> T:
        """Rate limit function calls."""
        await self.acquire()
        return await func()


class CircuitBreaker:
    """Circuit breaker for handling failures."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        """
        Initialize the circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.circuit_open = False
    
    async def call(self, func: Callable[..., T]) -> T:
        """
        Call function with circuit breaker logic.
        
        Args:
            func: Function to call
            
        Returns:
            Function result
            
        Raises:
            Exception: If circuit is open and function fails
        """
        if self.circuit_open:
            if self._should_attempt_recovery():
                logger.info("Attempting circuit recovery...")
                self.circuit_open = False
            else:
                logger.error("Circuit is open, call failed")
                raise RuntimeError("Circuit breaker is open")
        
        try:
            result = await func()
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self) -> None:
        """Handle successful call."""
        self.failure_count = 0
        self.last_failure_time = None
    
    def _on_failure(self) -> None:
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.circuit_open = True
            logger.error(
                f"Circuit opened after {self.failure_count} failures. "
                f"Will attempt recovery after {self.recovery_timeout}s"
            )
    
    def _should_attempt_recovery(self) -> bool:
        """Check if circuit should attempt recovery."""
        if self.last_failure_time is None:
            return False
        
        return time.time() - self.last_failure_time >= self.recovery_timeout


def validate_url(url: str) -> bool:
    """
    Validate URL format.
    
    Args:
        url: URL to validate
        
    Returns:
        True if URL is valid
    """
    import re
    
    pattern = r'^https?://[^\s/$.?#].[^\s]*$'
    return bool(re.match(pattern, url))


def validate_api_key(api_key: str) -> bool:
    """
    Validate API key format.
    
    Args:
        api_key: API key to validate
        
    Returns:
        True if API key is valid
    """
    return len(api_key) > 10


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to remove invalid characters.
    
    Args:
        filename: Filename to sanitize
        
    Returns:
        Sanitized filename
    """
    import re
    
    # Remove or replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove leading/trailing dots and spaces
    sanitized = sanitized.strip('. ')
    # Limit length
    return sanitized[:255]


async def wait_for_condition(
    condition: Callable[[], bool],
    timeout: float = 30.0,
    interval: float = 1.0,
) -> bool:
    """
    Wait for a condition to become true.
    
    Args:
        condition: Function that returns True when condition is met
        timeout: Maximum time to wait in seconds
        interval: Check interval in seconds
    
    Returns:
        True if condition became true, False if timeout
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if condition():
            return True
        await asyncio.sleep(interval)
    
    return False
