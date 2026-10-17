"""List a channel and save one Markdown transcript per video."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, TextIO

from supadata.types import BatchJob

from channel_transcripts.api import (
    PRICING_URL,
    ApiCaller,
    BudgetExceeded,
    QuotaExceeded,
    is_transcript_unavailable,
    select_video_ids,
)
from channel_transcripts.markdown import (
    ManifestError,
    atomic_write,
    load_manifest,
    render_markdown,
    save_manifest,
    transcript_path,
)


class ListingError(Exception):
    """The channel video list could not be read. No transcripts were requested."""

    def __init__(self, message: str, summary: Summary) -> None:
        super().__init__(message)
        self.summary = summary


class AsyncTranscript(Exception):
    """The SDK returned a job id instead of transcript text."""


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def transcript_mode(allow_generated: bool) -> str:
    """Native captions only, unless the user opts into the SDK's auto mode.

    ``mode="auto"`` tries a native transcript and may fall back to AI generation.
    ``mode="generate"`` is not used: ``--allow-generated`` permits generation,
    it does not force it when a native transcript already exists.
    """
    return "auto" if allow_generated else "native"


def redact(text: str, secret: str | None) -> str:
    if not secret or secret not in text:
        return text
    return text.replace(secret, "[REDACTED]")


@dataclass
class Summary:
    listed: int = 0
    skipped_existing: int = 0
    fetched: int = 0
    no_transcript: int = 0
    errors: int = 0
    calls_made: int = 0
    would_fetch: int = 0
    budget_stopped: int = 0
    dry_run: bool = False
    quota_stopped: bool = False

    def lines(self) -> list[str]:
        rows = [
            f"listed: {self.listed}",
            f"skipped_existing: {self.skipped_existing}",
            f"fetched: {self.fetched}",
            f"no_transcript: {self.no_transcript}",
            f"errors: {self.errors}",
            f"calls_made: {self.calls_made}",
        ]
        if self.dry_run:
            rows.append(f"would_fetch: {self.would_fetch}")
        if self.budget_stopped:
            rows.append(f"budget_stopped: {self.budget_stopped}")
        if self.quota_stopped:
            rows.append("quota_stopped: yes")
        rows.append(f"credit_cost: not calculated; see {PRICING_URL}")
        return rows


def _iso_z(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc).replace(microsecond=0)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _has_room(caller: ApiCaller, reserved: int) -> bool:
    if caller.max_calls is None:
        return True
    return caller.calls + reserved < caller.max_calls


def _count_unreached(summary: Summary, output_dir: Path, video_ids: list[str]) -> None:
    """Bucket ids left after a budget stop with the loop's own skip check.

    Saved ids count as ``skipped_existing`` and bad ids as ``errors``, as the
    loop would have counted them. Only ids that still need a call count as
    ``budget_stopped``, so each listed id lands in exactly one bucket.
    """
    for video_id in video_ids:
        try:
            path = transcript_path(output_dir, video_id)
        except ValueError:
            summary.errors += 1
            continue
        if path.is_file():
            summary.skipped_existing += 1
        else:
            summary.budget_stopped += 1


def _installed_supadata_version() -> str:
    try:
        return version("supadata")
    except PackageNotFoundError:
        return "unknown"


def _plain_text(result: Any) -> tuple[str, str]:
    job_id = getattr(result, "job_id", None)
    if isinstance(result, BatchJob) or (job_id and not hasattr(result, "content")):
        raise AsyncTranscript(
            f"supadata {_installed_supadata_version()} returned job "
            f"{job_id} and has no transcript.get_job_status method. "
            "Native YouTube transcripts are normally returned inline."
        )
    content = getattr(result, "content", None)
    lang = getattr(result, "lang", "") or ""
    if isinstance(content, str):
        return content.strip(), lang
    if isinstance(content, list):
        parts: list[str] = []
        for chunk in content:
            text = getattr(chunk, "text", None)
            if text is None and isinstance(chunk, dict):
                text = chunk.get("text", "")
            if text:
                parts.append(str(text).strip())
        return "\n".join(parts).strip(), lang
    return "", lang


def _transcript_kwargs(url: str, *, lang: str | None, mode: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"url": url, "text": True, "mode": mode}
    if lang:
        kwargs["lang"] = lang
    return kwargs


def list_channel(
    client: Any,
    caller: ApiCaller,
    *,
    channel: str,
    limit: int | None,
    video_type: str,
) -> list[str]:
    def _fetch() -> Any:
        kwargs: dict[str, Any] = {"id": channel, "type": video_type}
        if limit is not None:
            kwargs["limit"] = limit
        return client.youtube.channel.videos(**kwargs)

    return select_video_ids(caller.call(_fetch), video_type)


def _finish(summary: Summary, caller: ApiCaller) -> Summary:
    summary.calls_made = caller.calls
    return summary


def _fail(summary: Summary, caller: ApiCaller, exc: BaseException, secret: str | None) -> ListingError:
    summary.calls_made = caller.calls
    return ListingError(redact(str(exc), secret), summary)


def run_fetch(
    client: Any,
    *,
    channel: str,
    output_dir: Path,
    limit: int | None = None,
    video_type: str = "all",
    lang: str | None = None,
    allow_generated: bool = False,
    max_credits: int | None = None,
    dry_run: bool = False,
    with_titles: bool = False,
    secret: str | None = None,
    sleep: Callable[[float], None] | None = None,
    now: Callable[[], datetime] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    max_attempts: int = 5,
) -> Summary:
    """List videos, skip files already saved, and write the rest.

    A video is skipped when ``{output}/{video_id}.md`` already exists. The
    manifest records successful saves. If that file is missing, the video is
    fetched again even when the manifest still mentions it.
    """
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    clock = now or (lambda: datetime.now(timezone.utc))
    caller = ApiCaller(
        max_calls=max_credits,
        sleep=sleep or time.sleep,
        max_attempts=max_attempts,
    )
    summary = Summary(dry_run=dry_run)
    mode = transcript_mode(allow_generated)

    try:
        manifest = load_manifest(output_dir)
    except ManifestError as exc:
        raise _fail(summary, caller, exc, secret) from exc

    if not caller.can_attempt():
        print(
            "max-credits is 0; no API calls were made. "
            f"Pricing: {PRICING_URL}",
            file=err,
        )
        return _finish(summary, caller)

    if allow_generated and not dry_run:
        print(
            "allow-generated: using transcript mode=auto "
            "(native first, AI only if none exists). "
            f"Generation is billed by video length: {PRICING_URL}",
            file=err,
        )

    try:
        video_ids = list_channel(
            client,
            caller,
            channel=channel,
            limit=limit,
            video_type=video_type,
        )
    except (BudgetExceeded, QuotaExceeded, Exception) as exc:
        if isinstance(exc, QuotaExceeded):
            summary.quota_stopped = True
        summary.errors += 1
        raise _fail(summary, caller, exc, secret) from exc

    summary.listed = len(video_ids)
    print(f"listing {channel}: {summary.listed} videos", file=err)
    reserved = 0

    for index, video_id in enumerate(video_ids):
        try:
            path = transcript_path(output_dir, video_id)
        except ValueError as exc:
            summary.errors += 1
            print(f"error {video_id}: {redact(str(exc), secret)}", file=err)
            continue

        if path.is_file():
            summary.skipped_existing += 1
            print(f"skip existing {path.name}", file=err)
            continue

        if not _has_room(caller, reserved):
            _count_unreached(summary, output_dir, video_ids[index:])
            print(
                f"stopped: --max-credits ({max_credits} API calls) reached. "
                f"Pricing: {PRICING_URL}",
                file=err,
            )
            break

        url = video_url(video_id)
        if dry_run:
            summary.would_fetch += 1
            reserved += 1
            title_note = ""
            if with_titles and _has_room(caller, reserved):
                reserved += 1
                title_note = " + title"
            elif with_titles:
                title_note = " (title skipped: call cap)"
            print(f"would_fetch {video_id} {url}{title_note}", file=out)
            continue

        try:
            result = caller.call(
                lambda url=url: client.transcript(
                    **_transcript_kwargs(url, lang=lang, mode=mode)
                )
            )
            body, result_lang = _plain_text(result)
        except BudgetExceeded:
            _count_unreached(summary, output_dir, video_ids[index:])
            print(
                f"stopped during {video_id}: --max-credits reached. "
                f"Pricing: {PRICING_URL}",
                file=err,
            )
            break
        except QuotaExceeded as exc:
            summary.errors += 1
            summary.quota_stopped = True
            print(f"quota {video_id}: {redact(str(exc), secret)}", file=err)
            break
        except Exception as exc:
            if is_transcript_unavailable(exc):
                summary.no_transcript += 1
                print(f"no transcript {video_id}", file=err)
            else:
                summary.errors += 1
                print(f"error {video_id}: {redact(str(exc), secret)}", file=err)
            continue

        if not body:
            summary.no_transcript += 1
            print(f"no transcript {video_id}", file=err)
            continue

        title, stop_for_quota = _maybe_title(
            client,
            caller,
            url=url,
            video_id=video_id,
            with_titles=with_titles,
            secret=secret,
            err=err,
        )
        _write_transcript(
            output_dir,
            manifest,
            channel=channel,
            video_id=video_id,
            title=title,
            url=url,
            lang=result_lang or (lang or ""),
            fetched_at=_iso_z(clock()),
            body=body,
        )
        summary.fetched += 1
        print(f"saved {video_id}.md", file=err)
        if stop_for_quota:
            summary.quota_stopped = True
            break

    return _finish(summary, caller)


def _maybe_title(
    client: Any,
    caller: ApiCaller,
    *,
    url: str,
    video_id: str,
    with_titles: bool,
    secret: str | None,
    err: TextIO,
) -> tuple[str | None, bool]:
    if not with_titles or not caller.can_attempt():
        return None, False
    try:
        metadata = caller.call(lambda: client.metadata(url=url))
    except QuotaExceeded as exc:
        print(
            f"quota while reading title for {video_id}: {redact(str(exc), secret)}",
            file=err,
        )
        return None, True
    except BudgetExceeded:
        return None, False
    except Exception as exc:
        print(
            f"title unavailable {video_id}: {redact(str(exc), secret)}",
            file=err,
        )
        return None, False
    title = getattr(metadata, "title", None)
    if isinstance(title, str) and title.strip():
        return title.strip(), False
    return None, False


def _write_transcript(
    output_dir: Path,
    manifest: dict,
    *,
    channel: str,
    video_id: str,
    title: str | None,
    url: str,
    lang: str,
    fetched_at: str,
    body: str,
) -> None:
    text = render_markdown(
        video_id=video_id,
        title=title,
        url=url,
        channel=channel,
        lang=lang,
        fetched_at=fetched_at,
        body=body,
    )
    atomic_write(transcript_path(output_dir, video_id), text)
    manifest["channel"] = channel
    entry = {
        "video_id": video_id,
        "path": f"{video_id}.md",
        "url": url,
        "lang": lang,
        "fetched_at": fetched_at,
        "source": "supadata",
    }
    if title:
        entry["title"] = title
    manifest.setdefault("videos", {})[video_id] = entry
    save_manifest(output_dir, manifest)


def run_list(
    client: Any,
    *,
    channel: str,
    limit: int | None,
    video_type: str,
    secret: str | None = None,
    sleep: Callable[[float], None] | None = None,
    max_attempts: int = 5,
) -> tuple[list[str], Summary]:
    caller = ApiCaller(
        max_calls=None,
        sleep=sleep or time.sleep,
        max_attempts=max_attempts,
    )
    summary = Summary()
    try:
        video_ids = list_channel(
            client,
            caller,
            channel=channel,
            limit=limit,
            video_type=video_type,
        )
    except Exception as exc:
        if isinstance(exc, QuotaExceeded):
            summary.quota_stopped = True
        summary.errors += 1
        raise _fail(summary, caller, exc, secret) from exc
    summary.listed = len(video_ids)
    return video_ids, _finish(summary, caller)
