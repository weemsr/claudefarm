#!/usr/bin/env python3
"""First-cut Twitter timeline capture.

Single-shot: dumps the current X timeline state via adb, parses the UI
hierarchy for tweet rows, writes one JSON file per capture with parsed
metadata plus the raw screenshot + UI dump alongside it.

No scrolling, no uiautomator2 yet. Pure stdlib so it runs without uv sync.

Usage:
    python3 capture_twitter.py [output_root]

Output layout:
    <output_root>/<YYYY-MM-DD>/<serial>_<UTCstamp>_screen.png
    <output_root>/<YYYY-MM-DD>/<serial>_<UTCstamp>_ui.xml
    <output_root>/<YYYY-MM-DD>/<serial>_<UTCstamp>_tweets.json
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

PKG = "com.twitter.android"
ROW_OUTER_ID = f"{PKG}:id/outer_layout_row_view_tweet"
ROW_INNER_ID = f"{PKG}:id/row"
BODY_ID = f"{PKG}:id/tweet_content_text"

COUNTS_RE = re.compile(
    r"(?P<replies>\d+)\s+replies\.\s+"
    r"(?P<reposts>\d+)\s+reposts\.\s+"
    r"(?P<likes>\d+)\s+likes"
    r"(?:\.\s+(?P<views>\d+)\s+(?:verified\s+)?views)?",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"(\d+\s+\w+\s+ago)", re.IGNORECASE)
AUTHOR_RE = re.compile(r"^(?P<display>[^@]+?)\s+@(?P<handle>\w+)\b")
VERIFIED_RE = re.compile(r"@\w+\s+Verified\b", re.IGNORECASE)
BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def adb(*args: str) -> str:
    return subprocess.check_output(["adb", *args], text=True)


def device_serial() -> str:
    lines = adb("devices").strip().splitlines()
    devices = [ln.split("\t")[0] for ln in lines[1:] if ln.endswith("\tdevice")]
    if not devices:
        sys.exit("ERROR: no authorized ADB device found. Run `adb devices`.")
    if len(devices) > 1:
        sys.exit(f"ERROR: multiple devices attached, pick one: {devices}")
    return devices[0]


def capture_on_device() -> None:
    subprocess.check_call(["adb", "shell", "screencap", "-p", "/sdcard/screen.png"])
    subprocess.check_call(
        ["adb", "shell", "uiautomator", "dump", "/sdcard/ui.xml"],
        stdout=subprocess.DEVNULL,
    )


def pull(remote: str, local: Path) -> None:
    subprocess.check_call(["adb", "pull", remote, str(local)], stdout=subprocess.DEVNULL)


def parse_bounds(raw: str) -> list[int] | None:
    m = BOUNDS_RE.match(raw)
    return [int(x) for x in m.groups()] if m else None


def descendants_with_id(node: ET.Element, resource_id: str):
    for child in node.iter("node"):
        if child.get("resource-id") == resource_id:
            yield child


def body_text(outer: ET.Element) -> str:
    for body_container in descendants_with_id(outer, BODY_ID):
        for inner in body_container.iter("node"):
            text = inner.get("text") or ""
            if text:
                return text
    return ""


def parse_tweet(outer: ET.Element) -> dict | None:
    inner = next(iter(descendants_with_id(outer, ROW_INNER_ID)), None)
    if inner is None:
        return None
    desc = inner.get("content-desc") or ""
    if not desc:
        return None

    counts = COUNTS_RE.search(desc)
    author = AUTHOR_RE.match(desc)
    age = TIME_RE.search(desc)
    body = body_text(outer)

    payload: dict = {
        "display_name": author.group("display").strip() if author else None,
        "handle": author.group("handle") if author else None,
        "verified": bool(VERIFIED_RE.search(desc)),
        "body": body,
        "age": age.group(1) if age else None,
        "replies": int(counts.group("replies")) if counts else None,
        "reposts": int(counts.group("reposts")) if counts else None,
        "likes": int(counts.group("likes")) if counts else None,
        "views": int(counts.group("views")) if counts and counts.group("views") else None,
        "bounds": parse_bounds(outer.get("bounds", "")),
        "content_desc": desc,
    }
    fingerprint = f"{payload['handle']}|{payload['body']}|{desc[:200]}"
    payload["id"] = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return payload


def main() -> None:
    out_root = Path(sys.argv[1] if len(sys.argv) > 1 else "./twitter_captures").expanduser()
    serial = device_serial()

    now = datetime.now(timezone.utc)
    day_dir = out_root / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{serial}_{now.strftime('%Y%m%dT%H%M%SZ')}"
    png_path = day_dir / f"{prefix}_screen.png"
    xml_path = day_dir / f"{prefix}_ui.xml"
    json_path = day_dir / f"{prefix}_tweets.json"

    print(f"capturing from {serial} -> {day_dir}")
    capture_on_device()
    pull("/sdcard/screen.png", png_path)
    pull("/sdcard/ui.xml", xml_path)

    tree = ET.parse(xml_path)
    tweets = []
    for outer in tree.iter("node"):
        if outer.get("resource-id") == ROW_OUTER_ID:
            parsed = parse_tweet(outer)
            if parsed is not None:
                tweets.append(parsed)

    manifest = {
        "captured_at": now.isoformat(),
        "device_serial": serial,
        "source_app": PKG,
        "screen_png": png_path.name,
        "ui_xml": xml_path.name,
        "tweet_count": len(tweets),
        "tweets": tweets,
    }
    json_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    print(f"wrote {len(tweets)} tweets -> {json_path.name}")
    for t in tweets:
        snippet = (t["body"] or "<media-only / no text>")[:80].replace("\n", " ")
        print(f"  - @{t['handle']}: {snippet}")


if __name__ == "__main__":
    main()
