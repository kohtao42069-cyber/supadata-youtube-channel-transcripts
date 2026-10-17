# YouTube channel to transcripts

[![Powered by Supadata](https://img.shields.io/badge/Powered%20by-Supadata-111111?style=flat&labelColor=111111&color=3b82f6)](https://supadata.ai)

[![tests](https://github.com/kohtao42069-cyber/supadata-youtube-channel-transcripts/actions/workflows/ci.yml/badge.svg)](https://github.com/kohtao42069-cyber/supadata-youtube-channel-transcripts/actions/workflows/ci.yml)

Save a YouTube channel's transcripts as one Markdown file per video. The command line tool calls the official [Supadata Python SDK](https://pypi.org/project/supadata/) (`supadata` on PyPI, written against 1.6.0).

It lists uploads with `youtube.channel.videos`, then requests each transcript with `transcript(..., text=True, mode="native")`. Native captions are the default. AI generation stays off unless you pass `--allow-generated`, which switches the call to `mode="auto"` (native first, generate only if none exists).

## Setup

Create an API key at [dash.supadata.ai](https://dash.supadata.ai) and export it. The program reads `SUPADATA_API_KEY` from the environment. It has no key flag, and it does not print the value.

```bash
export SUPADATA_API_KEY="your-key"
```

Python 3.10 or newer:

```bash
pip install -e ".[dev]"
```

That installs this package and the `supadata` dependency. Use `channel-transcripts`, or `python -m channel_transcripts` if the script directory is not on your `PATH`.

## Usage

`CHANNEL` accepts an `@handle`, a channel URL, or a channel id. The SDK forwards that string as the `id` parameter.

Pass `--lang` when you care which captions you get. If you omit it, Supadata returns the first available caption language, which may not be the language spoken in the video ([transcript languages](https://docs.supadata.ai/get-transcript)). `--lang en` asks for English, and still falls back to that first available language when no English track exists. An English video can come back as `lang: de`. The fetch example asks for English.

```bash
channel-transcripts list "@ExampleChannel" --type video --limit 5

channel-transcripts fetch "@ExampleChannel" \
  --type video \
  --limit 2 \
  --lang en \
  --output ./out
```

Running `fetch` again skips any `{video_id}.md` that is already in the output directory. `manifest.json` records successful saves. If you delete a Markdown file, that video is fetched again.

### Illustrative output

The transcript text and the counts below are **illustrative**. They are not a captured Supadata response, and `abcdefghijk` is not a real video id.

```text
listed: 2
skipped_existing: 0
fetched: 1
no_transcript: 1
errors: 0
calls_made: 3
credit_cost: not calculated; see https://supadata.ai/pricing
```

`out/abcdefghijk.md`:

```markdown
---
video_id: abcdefghijk
url: https://www.youtube.com/watch?v=abcdefghijk
channel: "@ExampleChannel"
lang: en
fetched_at: 2026-10-17T13:00:00Z
source: supadata
---

This sentence stands in for a transcript.
```

A `title` line is added only when a title is available. Channel listing returns ids, not titles. `--with-titles` calls `metadata(url=...)` and writes `metadata.title` when the response includes one. That is an extra API call per video.

Check a run before spending transcript calls:

```bash
channel-transcripts fetch "@ExampleChannel" --limit 10 --dry-run --max-credits 5
```

`--dry-run` still lists the channel (that is a real API call) and prints `would_fetch` for ids that are not already saved. It does not call `transcript`.

## Options

| Option | Command | Default | What it does |
| --- | --- | --- | --- |
| `CHANNEL` | list, fetch | | `@handle`, channel URL, or channel id. Passed as `id` to `youtube.channel.videos`. |
| `--limit` | list, fetch | SDK default (30) | Maximum ids to request. Integer from 1 to 5000. |
| `--type` | list, fetch | `all` | `all`, `video`, `short`, or `live`. Passed as `type`. |
| `--output` | fetch | `transcripts` | Directory for `{video_id}.md` and `manifest.json`. |
| `--lang` | fetch | omitted | Preferred language, ISO 639-1, passed as `lang`. Without it, any available caption language may come back. `--lang en` still falls back to the first available language when English is missing. |
| `--allow-generated` | fetch | off | `mode="auto"` instead of `mode="native"`. |
| `--max-credits` | fetch | no cap | Stop before the next API call once this many calls have been made, including the listing and retries. |
| `--dry-run` | fetch | off | List the channel and print what would be fetched. |
| `--with-titles` | fetch | off | Call `metadata` for a title after a transcript is saved. |

`list` prints one video id per line, then the same style of summary (`listed`, `calls_made`).

## Credits

This tool counts API calls. It does not calculate a credit total. Supadata bills each call according to [the pricing page](https://supadata.ai/pricing). The SDK objects used here do not expose the `x-billable-requests` response header, so `--max-credits` is a cap on calls, not a price. Compare `calls_made` with that page for your plan. Generated transcripts are priced by video length; `--allow-generated` can cost more per call than a native transcript.

A per-video failure (including "no transcript") does not stop the run. The process exits 0 when the run finishes, including when some videos are counted under `errors` or `no_transcript`. It exits 1 when the channel list fails or a plan quota stops the run, and 2 when the key or the arguments are invalid. Rate limits (`limit-exceeded` with a rate-limit detail, or HTTP 429) are retried with backoff: 1s, 2s, 4s, 8s, up to five attempts. A plan usage limit stops the run. Every attempt counts in `calls_made`.

## Tests

```bash
pytest -q
```

The tests mock the SDK. They do not use the network and they do not need `SUPADATA_API_KEY`.

See [TUTORIAL.md](TUTORIAL.md) for how the calls fit together and how to change the template.

## SDK methods

| Method | Role |
| --- | --- |
| `Supadata(api_key=...)` | Client. The key comes from `SUPADATA_API_KEY`. |
| `youtube.channel.videos(id=, type=, limit=)` | List regular videos, Shorts, and live ids. |
| `transcript(url=, lang=, text=True, mode=)` | Plain-text transcript. `mode` is `native` or `auto`. |
| `metadata(url=)` | Optional title via `--with-titles`. |
