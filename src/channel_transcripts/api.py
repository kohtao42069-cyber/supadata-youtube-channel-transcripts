"""Call counting, rate-limit backoff, and channel id selection.

Credit prices are not encoded here. Supadata bills each API call according
to https://supadata.ai/pricing. This module only counts calls the SDK makes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from supadata.errors import SupadataError

PRICING_URL = "https://supadata.ai/pricing"
VIDEO_TYPES = ("all", "video", "short", "live")

T = TypeVar("T")


class BudgetExceeded(Exception):
    """The next API call would pass --max-credits."""


class QuotaExceeded(Exception):
    """The account's plan usage limit was exceeded. Retrying will not help."""


def _status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def _limit_text(exc: BaseException) -> str:
    parts: list[str] = [str(exc)]
    if isinstance(exc, SupadataError):
        parts.extend([exc.error or "", exc.message or "", exc.details or ""])
    code = _status_code(exc)
    if code is not None:
        parts.append(str(code))
    response = getattr(exc, "response", None)
    text = getattr(response, "text", None)
    if isinstance(text, str):
        parts.append(text)
    return " ".join(parts).lower()


def is_quota_limit(exc: BaseException) -> bool:
    """True for a monthly usage / quota 429, which backoff cannot clear."""
    text = _limit_text(exc)
    if "limit-exceeded" not in text and "429" not in text:
        return False
    return "plan usage" in text or "quota" in text


def is_rate_limit(exc: BaseException) -> bool:
    """True for a retryable request-rate 429."""
    if is_quota_limit(exc):
        return False
    if isinstance(exc, SupadataError) and exc.error == "limit-exceeded":
        return True
    return _status_code(exc) == 429


def is_transcript_unavailable(exc: BaseException) -> bool:
    return isinstance(exc, SupadataError) and exc.error == "transcript-unavailable"


class ApiCaller:
    """Count every SDK attempt, including retries, and back off on rate limits."""

    def __init__(
        self,
        *,
        max_calls: int | None,
        sleep: Callable[[float], None],
        max_attempts: int = 5,
    ) -> None:
        if max_calls is not None and max_calls < 0:
            raise ValueError("max_credits must be zero or a positive integer")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.max_calls = max_calls
        self.sleep = sleep
        self.max_attempts = max_attempts
        self.calls = 0

    def can_attempt(self) -> bool:
        return self.max_calls is None or self.calls < self.max_calls

    def call(self, fn: Callable[[], T]) -> T:
        delay = 1.0
        for attempt in range(1, self.max_attempts + 1):
            if not self.can_attempt():
                raise BudgetExceeded(
                    "Stopped before another API call because --max-credits was reached. "
                    f"Credit prices are on {PRICING_URL}."
                )
            self.calls += 1
            try:
                return fn()
            except BudgetExceeded:
                raise
            except Exception as exc:
                if is_quota_limit(exc):
                    raise QuotaExceeded(str(exc)) from exc
                retry = is_rate_limit(exc) and attempt < self.max_attempts
                if retry and not self.can_attempt():
                    retry = False
                if not retry:
                    raise
                self.sleep(delay)
                delay = min(delay * 2, 32.0)
        raise RuntimeError("rate-limit retry loop ended without a result")


def select_video_ids(payload: Any, video_type: str) -> list[str]:
    """Keep the id lists `youtube.channel.videos` returns for the requested type.

    For ``all``, ids stay in list order: regular videos, then Shorts, then live.
    Supadata documents that a ``type=all`` limit fills those groups in that
    order: https://docs.supadata.ai/youtube/channel-videos
    """
    if video_type not in VIDEO_TYPES:
        raise ValueError(f"type must be one of: {', '.join(VIDEO_TYPES)}")
    video_ids = list(getattr(payload, "video_ids", None) or [])
    short_ids = list(getattr(payload, "short_ids", None) or [])
    live_ids = list(getattr(payload, "live_ids", None) or [])
    if video_type == "video":
        ordered = video_ids
    elif video_type == "short":
        ordered = short_ids
    elif video_type == "live":
        ordered = live_ids
    else:
        ordered = [*video_ids, *short_ids, *live_ids]
    seen: set[str] = set()
    selected: list[str] = []
    for video_id in ordered:
        if not isinstance(video_id, str) or video_id in seen:
            continue
        seen.add(video_id)
        selected.append(video_id)
    return selected
