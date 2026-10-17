import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from supadata.errors import SupadataError
from supadata.types import BatchJob, Transcript

from channel_transcripts.runner import ListingError, run_fetch, run_list
from tests.fakes import FakeClient

WHEN = datetime(2026, 10, 17, 13, 0, tzinfo=timezone.utc)
VIDS = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]


def _fetch(client, tmp_path, **kwargs):
    params = dict(
        channel="@ExampleChannel",
        output_dir=tmp_path,
        limit=10,
        video_type="all",
        now=lambda: WHEN,
        sleep=lambda _seconds: None,
    )
    params.update(kwargs)
    return run_fetch(client, **params)


def test_fetch_writes_markdown_and_manifest(tmp_path):
    client = FakeClient()
    summary = _fetch(client, tmp_path)
    text = (tmp_path / "aaaaaaaaaaa.md").read_text(encoding="utf-8")
    assert "source: supadata" in text
    assert "Hello from the test." in text
    assert "title:" not in text
    assert summary.listed == 1
    assert summary.fetched == 1
    assert summary.calls_made == 2
    assert client.transcript_calls == [
        {
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "text": True,
            "mode": "native",
        }
    ]
    assert client.video_calls == [
        {"id": "@ExampleChannel", "type": "all", "limit": 10}
    ]
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["videos"]["aaaaaaaaaaa"]["source"] == "supadata"
    assert manifest["videos"]["aaaaaaaaaaa"]["lang"] == "en"


def test_second_run_skips_existing_file(tmp_path):
    client = FakeClient()
    _fetch(client, tmp_path)
    again = _fetch(client, tmp_path)
    assert again.skipped_existing == 1
    assert again.fetched == 0
    assert len(client.transcript_calls) == 1
    assert again.calls_made == 1


def test_type_short_passes_through_and_ignores_other_lists(tmp_path):
    client = FakeClient()
    client.videos_result = SimpleNamespace(
        video_ids=["aaaaaaaaaaa"],
        short_ids=["sssssssssss"],
        live_ids=["lllllllllll"],
    )
    summary = _fetch(client, tmp_path, video_type="short", limit=None)
    assert summary.fetched == 1
    assert (tmp_path / "sssssssssss.md").is_file()
    assert not (tmp_path / "aaaaaaaaaaa.md").exists()
    assert client.video_calls == [{"id": "@ExampleChannel", "type": "short"}]
    assert client.transcript_calls[0]["url"].endswith("sssssssssss")


def test_lang_and_allow_generated_change_transcript_kwargs(tmp_path):
    client = FakeClient()
    _fetch(client, tmp_path, lang="es", allow_generated=True)
    assert client.transcript_calls[0]["lang"] == "es"
    assert client.transcript_calls[0]["mode"] == "auto"
    assert client.transcript_calls[0]["text"] is True


def test_dry_run_lists_work_and_does_not_fetch(tmp_path):
    client = FakeClient()
    client.videos_result = SimpleNamespace(video_ids=VIDS, short_ids=[], live_ids=[])
    (tmp_path / "aaaaaaaaaaa.md").write_text("already\n", encoding="utf-8")
    lines: list[str] = []

    class Buffer:
        def write(self, text):
            lines.append(text)
            return len(text)

    summary = _fetch(
        client,
        tmp_path,
        dry_run=True,
        max_credits=3,
        stdout=Buffer(),
    )
    assert client.transcript_calls == []
    assert summary.listed == 3
    assert summary.skipped_existing == 1
    assert summary.would_fetch == 2
    assert summary.fetched == 0
    assert summary.budget_stopped == 0
    assert summary.calls_made == 1
    printed = "".join(lines)
    assert "would_fetch bbbbbbbbbbb https://www.youtube.com/watch?v=bbbbbbbbbbb" in printed
    assert "would_fetch ccccccccccc" in printed
    assert not (tmp_path / "bbbbbbbbbbb.md").exists()


def test_dry_run_honors_call_cap_including_titles(tmp_path):
    client = FakeClient()
    client.videos_result = SimpleNamespace(video_ids=VIDS, short_ids=[], live_ids=[])

    class Sink:
        def write(self, text):
            return len(text)

        def flush(self):
            return None

    summary = _fetch(
        client,
        tmp_path,
        dry_run=True,
        with_titles=True,
        max_credits=3,
        stdout=Sink(),
    )
    # 1 listing call leaves room for one transcript plus one title.
    assert summary.would_fetch == 1
    assert summary.budget_stopped == 2
    assert summary.calls_made == 1
    assert client.metadata_calls == []


def test_max_credits_stops_before_extra_transcripts(tmp_path):
    client = FakeClient()
    client.videos_result = SimpleNamespace(video_ids=VIDS, short_ids=[], live_ids=[])
    summary = _fetch(client, tmp_path, max_credits=2)
    assert summary.listed == 3
    assert summary.fetched == 1
    assert summary.budget_stopped == 2
    assert summary.calls_made == 2
    assert len(client.transcript_calls) == 1
    assert (tmp_path / "aaaaaaaaaaa.md").is_file()
    assert not (tmp_path / "bbbbbbbbbbb.md").exists()


def test_zero_budget_makes_no_calls(tmp_path):
    client = FakeClient()
    summary = _fetch(client, tmp_path, max_credits=0)
    assert summary.calls_made == 0
    assert summary.listed == 0
    assert client.video_calls == []


def test_unavailable_and_other_errors_continue(tmp_path):
    client = FakeClient()
    client.videos_result = SimpleNamespace(video_ids=VIDS, short_ids=[], live_ids=[])
    seen = {"n": 0}

    def transcript(**_kwargs):
        seen["n"] += 1
        if seen["n"] == 1:
            raise SupadataError(
                error="transcript-unavailable",
                message="No Transcript",
                details="No transcript available",
            )
        if seen["n"] == 2:
            raise SupadataError(
                error="video-not-found",
                message="Not found",
                details="missing",
            )
        return Transcript(content="Third one.", lang="en", available_langs=["en"])

    client.transcript_impl = transcript
    summary = _fetch(client, tmp_path)
    assert summary.no_transcript == 1
    assert summary.errors == 1
    assert summary.fetched == 1
    assert summary.calls_made == 4
    assert (tmp_path / "ccccccccccc.md").is_file()
    assert not (tmp_path / "aaaaaaaaaaa.md").exists()


def test_empty_transcript_is_not_saved(tmp_path):
    client = FakeClient()
    client.transcript_impl = lambda **_kwargs: Transcript(
        content="   ",
        lang="en",
        available_langs=["en"],
    )
    summary = _fetch(client, tmp_path)
    assert summary.no_transcript == 1
    assert summary.fetched == 0
    assert list(tmp_path.glob("*.md")) == []


def test_async_job_is_an_error_on_sdk_1_6(tmp_path, capsys):
    client = FakeClient()
    client.transcript_impl = lambda **_kwargs: BatchJob(job_id="job_123")
    summary = _fetch(client, tmp_path)
    assert summary.errors == 1
    assert summary.fetched == 0
    assert "get_job_status" in capsys.readouterr().err


def test_rate_limit_then_success(tmp_path):
    client = FakeClient()
    sleeps: list[float] = []
    state = {"n": 0}

    def transcript(**_kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise SupadataError(
                error="limit-exceeded",
                message="Limit Exceeded",
                details="Global request rate limit was exceeded.",
            )
        return Transcript(content="After backoff.", lang="en", available_langs=["en"])

    client.transcript_impl = transcript
    summary = _fetch(client, tmp_path, sleep=sleeps.append)
    assert sleeps == [1.0]
    assert summary.fetched == 1
    assert summary.errors == 0
    assert summary.calls_made == 3
    assert "After backoff." in (tmp_path / "aaaaaaaaaaa.md").read_text(encoding="utf-8")


def test_quota_stops_the_run(tmp_path):
    client = FakeClient()
    client.videos_result = SimpleNamespace(
        video_ids=["aaaaaaaaaaa", "bbbbbbbbbbb"],
        short_ids=[],
        live_ids=[],
    )

    def transcript(**_kwargs):
        raise SupadataError(
            error="limit-exceeded",
            message="Limit Exceeded",
            details="Plan usage limit was exceeded.",
        )

    client.transcript_impl = transcript
    summary = _fetch(client, tmp_path)
    assert summary.quota_stopped is True
    assert summary.errors == 1
    assert summary.fetched == 0
    assert len(client.transcript_calls) == 1


def test_titles_use_metadata_and_survive_metadata_failure(tmp_path):
    client = FakeClient()
    summary = _fetch(client, tmp_path, with_titles=True)
    text = (tmp_path / "aaaaaaaaaaa.md").read_text(encoding="utf-8")
    assert 'title: "Example title"\n' in text
    assert summary.calls_made == 3
    assert client.metadata_calls == [
        {"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"}
    ]

    client.metadata_impl = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("metadata down"))
    (tmp_path / "aaaaaaaaaaa.md").unlink()
    summary = _fetch(client, tmp_path, with_titles=True)
    text = (tmp_path / "aaaaaaaaaaa.md").read_text(encoding="utf-8")
    assert "title:" not in text
    assert summary.fetched == 1
    assert summary.errors == 0


def test_secret_is_redacted(tmp_path, capsys):
    client = FakeClient()
    secret = "sd_test_secret_value_should_not_leak"
    client.transcript_impl = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError(f"server echoed {secret}")
    )
    summary = _fetch(client, tmp_path, secret=secret)
    captured = capsys.readouterr()
    assert secret not in captured.err
    assert secret not in captured.out
    assert "[REDACTED]" in captured.err
    assert summary.errors == 1


def test_corrupt_manifest_does_not_call_the_api(tmp_path):
    client = FakeClient()
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "manifest.json").write_text("{", encoding="utf-8")
    with pytest.raises(ListingError):
        _fetch(client, tmp_path)
    assert client.video_calls == []


def test_list_prints_ids_for_handle_url_shape():
    client = FakeClient()
    client.videos_result = SimpleNamespace(
        video_ids=["aaaaaaaaaaa"],
        short_ids=["sssssssssss"],
        live_ids=[],
    )
    ids, summary = run_list(
        client,
        channel="https://www.youtube.com/@ExampleChannel",
        limit=5,
        video_type="all",
        sleep=lambda _s: None,
    )
    assert ids == ["aaaaaaaaaaa", "sssssssssss"]
    assert summary.calls_made == 1
    assert client.video_calls[0]["id"] == "https://www.youtube.com/@ExampleChannel"


def test_listing_failure_raises_without_transcripts(tmp_path):
    client = FakeClient()

    def boom(**_kwargs):
        raise SupadataError(
            error="not-found",
            message="Not found",
            details="No channel",
        )

    client.videos_impl = boom
    with pytest.raises(ListingError) as caught:
        _fetch(client, tmp_path)
    assert caught.value.summary.calls_made == 1
    assert caught.value.summary.errors == 1
    assert client.transcript_calls == []
