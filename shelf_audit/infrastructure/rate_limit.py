"""
Simple rate limiting helpers for audit requests.

This module is intentionally provider-neutral and Streamlit-neutral.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimitError(RuntimeError):
    """Raised when a caller exceeds the allowed request rate."""


class MemoryRateLimiter:
    """
    Basic in-memory sliding-window rate limiter.

    Good for local development and early testing.
    Later this can be replaced with Redis or persistent storage.
    """

    def __init__(
        self,
        *,
        max_requests: int = 5,
        window_seconds: int = 60,
    ) -> None:

        if max_requests < 1:
            raise ValueError(
                "max_requests must be at least 1."
            )

        if window_seconds < 1:
            raise ValueError(
                "window_seconds must be at least 1."
            )

        self.max_requests = max_requests
        self.window_seconds = window_seconds

        self._requests: dict[str, deque[float]] = defaultdict(deque)


    def _cleanup(
        self,
        key: str,
        now: float,
    ) -> None:
        """
        Remove request timestamps that have fallen outside the window.
        """

        cutoff = now - self.window_seconds
        queue = self._requests[key]

        while queue and queue[0] <= cutoff:
            queue.popleft()


    def remaining(
        self,
        key: str,
    ) -> int:
        """
        Return how many requests remain in the current window.
        """

        now = time.time()

        self._cleanup(
            key,
            now,
        )

        used = len(
            self._requests[key]
        )

        return max(
            0,
            self.max_requests - used,
        )


    def check(
        self,
        key: str,
    ) -> None:
        """
        Raise RateLimitError if the caller has exceeded the limit.
        """

        now = time.time()

        self._cleanup(
            key,
            now,
        )

        queue = self._requests[key]

        if len(queue) >= self.max_requests:

            retry_after = (
                self.window_seconds
                - (now - queue[0])
            )

            raise RateLimitError(
                "Too many audit requests. "
                f"Try again in about {max(1, int(retry_after))} seconds."
            )


    def record(
        self,
        key: str,
    ) -> None:
        """
        Record a successful request attempt.
        """

        now = time.time()

        self._cleanup(
            key,
            now,
        )

        self._requests[key].append(
            now
        )


    def check_and_record(
        self,
        key: str,
    ) -> None:
        """
        Validate and record a request in one step.
        """

        self.check(key)
        self.record(key)


    def clear(
        self,
        key: str | None = None,
    ) -> None:
        """
        Clear one caller or all rate-limit history.
        """

        if key is None:
            self._requests.clear()
            return

        self._requests.pop(
            key,
            None,
        )