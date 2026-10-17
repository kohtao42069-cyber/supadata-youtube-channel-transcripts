from types import SimpleNamespace

import pytest
from supadata.errors import SupadataError

from channel_transcripts.api import (
    ApiCaller,
    BudgetExceeded,
    QuotaExceeded,
    is_quota_limit,
    is_rate_limit,
    select_video_ids,
)


def test_select_video_ids_respects_type_and_dedupes():
    payload = SimpleNamespace(
        video_ids=["vidA", "vidA", "both"],
        short_ids=["short1", "both"],
        live_ids=["live1"],
    )
    assert select_video_ids(payload, "all") == ["vidA", "both", "short1", "live1"]
    assert select_video_ids(payload, "video") == ["vidA", "both"]
    assert select_video_ids(payload, "short") == ["short1", "both"]
    assert select_video_ids(payload, "live") == ["live1"]


def test_rate_limit_backoff_counts_every_attempt():
    sleeps: list[float] = []
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise SupadataError(
                error="limit-exceeded",
                message="Limit Exceeded",
                details="Request rate limit on current plan was exceeded.",
            )
        return "ok"

    caller = ApiCaller(max_calls=10, sleep=sleeps.append, max_attempts=5)
    assert caller.call(flaky) == "ok"
    assert caller.calls == 3
    assert sleeps == [1.0, 2.0]


def test_http_429_without_json_body_is_retried():
    class Http429(Exception):
        def __init__(self):
            super().__init__("too many requests")
            self.response = SimpleNamespace(status_code=429, text="too many requests")

    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] == 1:
            raise Http429()
        return "ok"

    caller = ApiCaller(max_calls=5, sleep=lambda _s: None, max_attempts=3)
    assert caller.call(flaky) == "ok"
    assert caller.calls == 2


def test_plan_usage_is_not_retried():
    def quota():
        raise SupadataError(
            error="limit-exceeded",
            message="Limit Exceeded",
            details="Plan usage limit was exceeded.",
        )

    caller = ApiCaller(max_calls=5, sleep=lambda _s: (_ for _ in ()).throw(AssertionError("slept")), max_attempts=4)
    with pytest.raises(QuotaExceeded):
        caller.call(quota)
    assert caller.calls == 1
    assert is_quota_limit(
        SupadataError(
            error="limit-exceeded",
            message="Limit Exceeded",
            details="Plan usage limit was exceeded.",
        )
    )
    assert not is_rate_limit(
        SupadataError(
            error="limit-exceeded",
            message="Limit Exceeded",
            details="Plan usage limit was exceeded.",
        )
    )


def test_budget_stops_before_the_call():
    caller = ApiCaller(max_calls=0, sleep=lambda _s: None)
    with pytest.raises(BudgetExceeded):
        caller.call(lambda: "nope")
    assert caller.calls == 0
