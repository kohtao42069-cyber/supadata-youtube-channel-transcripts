# Walkthrough

This template turns a public YouTube channel into one Markdown file per transcript. It calls Supadata only through the official `supadata` package on PyPI. The method names below are from version 1.6.0.

Put your API key in `SUPADATA_API_KEY`. The CLI passes it to `Supadata(api_key=...)` and does not print it. If an exception message contains the key, that text becomes `[REDACTED]`. There is no key flag.

## The two calls a fetch makes

A fetch lists the channel, then asks for each transcript that is not already on disk.

```python
from supadata import Supadata

supadata = Supadata(api_key=api_key)
listed = supadata.youtube.channel.videos(
    id=channel,    # @handle, channel URL, or channel id
    type="video",  # "all", "video", "short", or "live"
    limit=20,      # omit this for the SDK default of 30
)
```

`youtube.channel.videos` returns `VideoIds`: `video_ids`, `short_ids`, and `live_ids`. Your `id` string is forwarded as-is, and `--type` is forwarded as `type`. For `all`, this template keeps regular videos, then Shorts, then live ids, and drops duplicates. Supadata documents that a `type=all` limit fills those groups in that order ([channel videos](https://docs.supadata.ai/youtube/channel-videos)).

```python
transcript = supadata.transcript(
    url=f"https://www.youtube.com/watch?v={video_id}",
    lang="en",      # omitted unless you passed --lang
    text=True,      # a string, not timestamped chunks
    mode="native",  # "auto" only with --allow-generated
)
```

`text=True` puts a string on `transcript.content`. Otherwise `content` is a list of `TranscriptChunk` values (`text`, `offset`, `duration`, `lang`). `mode` is passed every time because the SDK default is `"auto"`, which can generate a transcript when YouTube has no captions. This tool sends `"native"` unless you pass `--allow-generated`, which switches the argument to `"auto"` (native first, generation only as a fallback). It does not send `"generate"`.

Leave `lang` out and Supadata returns the first available caption language, which may not be the language spoken in the video ([transcript languages](https://docs.supadata.ai/get-transcript)). An English video can come back as German. Pass `--lang en` when you want English. The saved `lang` field is the language Supadata actually returned.

`youtube.transcript.batch`, polled with `youtube.batch.get_batch_results`, is a different call. In 1.6.0 its inputs are video ids, a playlist id, or a channel id, plus optional `lang`, `text`, and `limit`. It has no `mode` argument, and the job is asynchronous. Per-video `transcript()` is how this template stays on native captions, skips a file it already wrote, and continues after one video fails. SDK 1.6.0 has no `transcript.get_job_status`. A `BatchJob` (a `job_id` and no content) is counted under `errors`. Native YouTube captions normally come back inline.

## Files

Each success is `{output}/{video_id}.md`. YAML front matter, a blank line, then the transcript with the ends trimmed:

```yaml
---
video_id: abcdefghijk
url: https://www.youtube.com/watch?v=abcdefghijk
channel: "@ExampleChannel"
lang: en
fetched_at: 2026-10-17T13:00:00Z
source: supadata
---
```

`source` is always `supadata`. The channel listing does not return titles, so `title` is omitted unless you pass `--with-titles`. That flag calls `supadata.metadata(url=...)` and copies `metadata.title` when it is a non-empty string. A metadata failure still keeps the transcript file, without a title. The lookup is another API call and counts toward `--max-credits`.

`manifest.json` records each saved video. The skip check is the `.md` file. Delete it and the next run fetches that id again. Leave it and the run counts `skipped_existing` and does not call `transcript`. The writer uses a temporary file and then replaces the destination, so a crash does not leave a partial file that a later run would treat as finished.

## Limits and failures

`SupadataError` carries `error`, `message`, `details`, and sometimes `documentation_url`. No native transcript is `error="transcript-unavailable"`. Supadata documents that response as HTTP 206 ([transcript unavailable](https://docs.supadata.ai/errors/transcript-unavailable)). That increments `no_transcript` and the loop continues. An empty string is treated the same way, and no file is written. Any other per-video exception increments `errors`. If the channel list fails, the process exits 1 and no transcript call is made.

HTTP 429 arrives as `error="limit-exceeded"`. A rate-limit detail, or a raw HTTP 429, is retried up to five attempts. The pause starts at one second and doubles: 1, 2, 4, then 8 seconds. "Plan usage limit was exceeded" is a quota, so the run stops and the process exits 1. Every attempt, including a 429, increments `calls_made`.

`--max-credits` caps how many attempts will start. The listing counts, and so does a retry. The SDK returns parsed objects, not the `x-billable-requests` header, so this program does not report a credit total and does not multiply calls by a price. The summary says the cost is not calculated and links to the pricing page, which is where a channel listing, a native transcript, and a generated minute are priced. `--dry-run` still lists the channel, prints `would_fetch` for ids that are not saved, and does not call `transcript` or `metadata`. The same cap applies.

## Changing it

To read a playlist, call `supadata.youtube.playlist.videos(id=..., limit=...)`. In 1.6.0 it returns the same `VideoIds` shape. Point `list_channel` at it. That method does not take `type`.

Edit `transcript_path` in `markdown.py` to change the layout. The skip check uses it, so a subdirectory has to stay consistent with the writer.

For timestamps, call `transcript` with `text=False` and format each `TranscriptChunk` in `render_markdown`. The plain-text string is in `run_fetch` just before `_write_transcript` if you want to process the words yourself. Count any extra API call in `calls_made`.

Tests build a fake client with `youtube.channel.videos`, `transcript`, and `metadata`. A socket guard fails the run if anything connects. Assert the keyword arguments you expect, including `mode="native"`.
