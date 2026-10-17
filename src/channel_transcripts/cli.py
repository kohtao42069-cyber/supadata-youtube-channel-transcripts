"""Command-line interface for channel transcripts."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from supadata import Supadata

from channel_transcripts.api import PRICING_URL, VIDEO_TYPES
from channel_transcripts.runner import ListingError, run_fetch, run_list

ENV_KEY = "SUPADATA_API_KEY"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="channel-transcripts",
        description=(
            "List a YouTube channel's videos and save native transcripts as "
            "Markdown using the official Supadata Python SDK."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser(
        "list",
        help="Print video ids from a channel",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_channel_args(list_parser)

    fetch_parser = sub.add_parser(
        "fetch",
        help="Save one Markdown transcript per video",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_channel_args(fetch_parser)
    fetch_parser.add_argument(
        "--output",
        default="transcripts",
        help="Directory for {video_id}.md files and manifest.json",
    )
    fetch_parser.add_argument(
        "--lang",
        default=None,
        help="Preferred transcript language (ISO 639-1), passed as lang",
    )
    fetch_parser.add_argument(
        "--allow-generated",
        action="store_true",
        help=(
            "Use transcript mode=auto, which may generate a transcript with AI "
            "when no native transcript exists. The default is mode=native."
        ),
    )
    fetch_parser.add_argument(
        "--max-credits",
        type=int,
        default=None,
        help=(
            "Maximum number of Supadata API calls for this run, including the "
            "channel listing and any retries. This tool does not price credits; "
            f"see {PRICING_URL}."
        ),
    )
    fetch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the channel, then print the videos that would be fetched",
    )
    fetch_parser.add_argument(
        "--with-titles",
        action="store_true",
        help=(
            "Call metadata for each saved video and store the title when one "
            "is returned. Each lookup is an extra API call."
        ),
    )
    return parser


def _add_channel_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "channel",
        help="YouTube @handle, channel URL, or channel id",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum video ids to request (1-5000). Omit for the SDK default of 30.",
    )
    parser.add_argument(
        "--type",
        dest="video_type",
        choices=VIDEO_TYPES,
        default="all",
        help="Which uploads to include. Passed to youtube.channel.videos.",
    )


def _validate(args: argparse.Namespace) -> str | None:
    if args.limit is not None and (args.limit < 1 or args.limit > 5000):
        return "--limit must be an integer from 1 to 5000"
    max_credits = getattr(args, "max_credits", None)
    if max_credits is not None and max_credits < 0:
        return "--max-credits must be zero or a positive integer"
    if not str(args.channel).strip():
        return "channel must not be empty"
    return None


def _api_key() -> str | None:
    value = os.environ.get(ENV_KEY, "").strip()
    return value or None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    problem = _validate(args)
    if problem:
        print(problem, file=sys.stderr)
        return 2

    key = _api_key()
    if key is None:
        print(
            f"Set {ENV_KEY} to your Supadata API key (https://dash.supadata.ai). "
            "The value is read from the environment and is not printed.",
            file=sys.stderr,
        )
        return 2

    client = Supadata(api_key=key)
    if args.command == "list":
        return _cmd_list(client, args, secret=key)
    return _cmd_fetch(client, args, secret=key)


def _cmd_list(client: Supadata, args: argparse.Namespace, *, secret: str) -> int:
    try:
        video_ids, summary = run_list(
            client,
            channel=args.channel,
            limit=args.limit,
            video_type=args.video_type,
            secret=secret,
        )
    except ListingError as exc:
        print(str(exc), file=sys.stderr)
        _print_summary(exc.summary)
        return 1
    for video_id in video_ids:
        print(video_id)
    _print_summary(summary)
    return 1 if summary.quota_stopped else 0


def _cmd_fetch(client: Supadata, args: argparse.Namespace, *, secret: str) -> int:
    try:
        summary = run_fetch(
            client,
            channel=args.channel,
            output_dir=Path(args.output),
            limit=args.limit,
            video_type=args.video_type,
            lang=args.lang,
            allow_generated=args.allow_generated,
            max_credits=args.max_credits,
            dry_run=args.dry_run,
            with_titles=args.with_titles,
            secret=secret,
        )
    except ListingError as exc:
        print(str(exc), file=sys.stderr)
        _print_summary(exc.summary)
        return 1
    _print_summary(summary)
    return 1 if summary.quota_stopped else 0


def _print_summary(summary) -> None:
    print("\n".join(summary.lines()))


if __name__ == "__main__":
    sys.exit(main())
