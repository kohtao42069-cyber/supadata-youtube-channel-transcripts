"""Markdown transcripts and the on-disk manifest."""

from __future__ import annotations

import json
import re
from pathlib import Path

_PLAIN = re.compile(r"[A-Za-z0-9_@./:?=&+-]+")
_YAML_RESERVED = {"true", "false", "null", "yes", "no", "on", "off"}
# Plain YAML cannot start with an indicator. '@jawed' is the case that breaks.
_YAML_INDICATORS = set("@`!&*|>%#'\"{}[],?:-")
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class ManifestError(ValueError):
    """The manifest file exists but is not usable."""


def yaml_scalar(value: str) -> str:
    """Quote a string so it is a single safe YAML scalar."""
    if _needs_quotes(value):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )
        return f'"{escaped}"'
    return value


def _needs_quotes(value: str) -> bool:
    if value == "" or value.lower() in _YAML_RESERVED or not _PLAIN.fullmatch(value):
        return True
    if value[0] in _YAML_INDICATORS:
        return True
    return ": " in value or " #" in value


def video_filename(video_id: str) -> str:
    if not _VIDEO_ID.fullmatch(video_id):
        raise ValueError(f"Refusing to write an unexpected video id: {video_id!r}")
    return f"{video_id}.md"


def render_markdown(
    *,
    video_id: str,
    title: str | None,
    url: str,
    channel: str,
    lang: str,
    fetched_at: str,
    body: str,
) -> str:
    """Build one transcript file: YAML front matter, then plain text."""
    lines = ["---", f"video_id: {yaml_scalar(video_id)}"]
    if title:
        lines.append(f"title: {yaml_scalar(title)}")
    lines.extend(
        [
            f"url: {yaml_scalar(url)}",
            f"channel: {yaml_scalar(channel)}",
            f"lang: {yaml_scalar(lang)}",
            f"fetched_at: {yaml_scalar(fetched_at)}",
            "source: supadata",
            "---",
            "",
            body.strip(),
            "",
        ]
    )
    return "\n".join(lines)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def transcript_path(output_dir: Path, video_id: str) -> Path:
    return output_dir / video_filename(video_id)


def manifest_path(output_dir: Path) -> Path:
    return output_dir / "manifest.json"


def load_manifest(output_dir: Path) -> dict:
    path = manifest_path(output_dir)
    if not path.exists():
        return {"videos": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("videos"), dict):
        raise ManifestError(f"Unexpected manifest shape in {path}")
    return data


def save_manifest(output_dir: Path, manifest: dict) -> None:
    path = manifest_path(output_dir)
    atomic_write(path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
