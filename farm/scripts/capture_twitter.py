#!/usr/bin/env python3
"""Scrolling X (Twitter) timeline capture with show-more expansion.

Scrolls the Home / For You timeline via ADB swipes, dumps the UI hierarchy
+ screenshot per page, parses every visible tweet, dedupes across pages by
content hash, and (best-effort) drills into truncated tweets to recover the
full body text.

Stdlib only. Run from any directory.

Usage:
    python3 capture_twitter.py [--output-root DIR] [--max-tweets N] ...

Output layout:
    <output_root>/<YYYY-MM-DD>/<serial>_<UTCstamp>_run.json    # final manifest
    <output_root>/<YYYY-MM-DD>/pages/<serial>_<UTCstamp>_page<NN>_screen.png
    <output_root>/<YYYY-MM-DD>/pages/<serial>_<UTCstamp>_page<NN>_ui.xml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

PKG = "com.twitter.android"
ROW_OUTER_ID = f"{PKG}:id/outer_layout_row_view_tweet"
ROW_INNER_ID = f"{PKG}:id/row"
BODY_ID = f"{PKG}:id/tweet_content_text"
HEADER_ID = f"{PKG}:id/tweet_header"
TIMELINE_LIST_ID = "android:id/list"
# Order matters: tweet_text is the focal-tweet body on the detail page (no truncation).
# tweet_content_text is the timeline-style body and kept as a fallback.
DETAIL_BODY_IDS = (f"{PKG}:id/tweet_text", BODY_ID)
# Markers used to detect tweets that embed video. Twitter project scrapes text;
# video tweets belong on the TikTok pipeline, and they also tend to expose their
# body through custom Views that uiautomator can't introspect.
VIDEO_MARKER_IDS = (f"{PKG}:id/video_container", f"{PKG}:id/video_player_view")

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

# X renders a trailing " Show more" link as plain text when a tweet is
# truncated in the timeline view. Strip it so the body field is clean.
SHOW_MORE_SUFFIX = " Show more"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def adb(*args: str, check: bool = True) -> str:
    return subprocess.run(
        ["adb", *args], capture_output=True, text=True, check=check
    ).stdout


def adb_shell(*args: str, check: bool = True) -> str:
    return adb("shell", *args, check=check)


def device_serial() -> str:
    lines = adb("devices").strip().splitlines()
    devices = [ln.split("\t")[0] for ln in lines[1:] if ln.endswith("\tdevice")]
    if not devices:
        sys.exit("ERROR: no authorized ADB device found.")
    if len(devices) > 1:
        sys.exit(f"ERROR: multiple devices attached, pick one: {devices}")
    return devices[0]


def ensure_twitter_foreground() -> None:
    """Launch X if it isn't already the foreground app."""
    log("ensuring X is in foreground")
    adb_shell(
        "monkey",
        "-p",
        PKG,
        "-c",
        "android.intent.category.LAUNCHER",
        "1",
        check=False,
    )
    time.sleep(2.0)


def dump_ui(local_xml: Path) -> bool:
    """Dump uiautomator hierarchy to /sdcard/ui.xml and pull it. Return True on success."""
    try:
        out = adb_shell("uiautomator", "dump", "/sdcard/ui.xml")
        if "ERROR" in out.upper():
            log(f"uiautomator dump returned: {out.strip()}")
            return False
        adb("pull", "/sdcard/ui.xml", str(local_xml), check=True)
        return local_xml.exists() and local_xml.stat().st_size > 0
    except subprocess.CalledProcessError as e:
        log(f"dump_ui failed: {e}")
        return False


def screencap(local_png: Path) -> bool:
    try:
        adb_shell("screencap", "-p", "/sdcard/screen.png")
        adb("pull", "/sdcard/screen.png", str(local_png), check=True)
        return local_png.exists() and local_png.stat().st_size > 0
    except subprocess.CalledProcessError as e:
        log(f"screencap failed: {e}")
        return False


def swipe_up(jitter_x: bool = True) -> None:
    """One page of upward scroll (= scroll feed down)."""
    base_x = 540
    x_off = random.randint(-60, 60) if jitter_x else 0
    duration_ms = random.randint(500, 800)
    y_start = random.randint(1750, 1900)
    y_end = random.randint(550, 700)
    adb_shell("input", "swipe", str(base_x + x_off), str(y_start),
              str(base_x + x_off), str(y_end), str(duration_ms))


def tap(x: int, y: int) -> None:
    adb_shell("input", "tap", str(x), str(y))


def press_back() -> None:
    adb_shell("input", "keyevent", "KEYCODE_BACK")


def parse_bounds(raw: str) -> list[int] | None:
    m = BOUNDS_RE.match(raw)
    return [int(x) for x in m.groups()] if m else None


def descendants_with_id(node: ET.Element, resource_id: str):
    for child in node.iter("node"):
        if child.get("resource-id") == resource_id:
            yield child


def first_text_under(outer: ET.Element, resource_id: str) -> str:
    for container in descendants_with_id(outer, resource_id):
        for inner in container.iter("node"):
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

    raw_body = first_text_under(outer, BODY_ID)
    truncated = raw_body.endswith(SHOW_MORE_SUFFIX)
    body = raw_body[: -len(SHOW_MORE_SUFFIX)].rstrip() if truncated else raw_body
    has_video = any(
        n.get("resource-id") in VIDEO_MARKER_IDS for n in outer.iter("node")
    )

    counts = COUNTS_RE.search(desc)
    author = AUTHOR_RE.match(desc)
    age = TIME_RE.search(desc)
    header = next(iter(descendants_with_id(outer, HEADER_ID)), None)
    header_bounds = parse_bounds(header.get("bounds", "")) if header is not None else None

    payload: dict = {
        "display_name": author.group("display").strip() if author else None,
        "handle": author.group("handle") if author else None,
        "verified": bool(VERIFIED_RE.search(desc)),
        "body": body,
        "truncated": truncated,
        "expanded": False,
        "has_video": has_video,
        "age": age.group(1) if age else None,
        "replies": int(counts.group("replies")) if counts else None,
        "reposts": int(counts.group("reposts")) if counts else None,
        "likes": int(counts.group("likes")) if counts else None,
        "views": int(counts.group("views")) if counts and counts.group("views") else None,
        "bounds": parse_bounds(outer.get("bounds", "")),
        "header_bounds": header_bounds,
        "content_desc": desc,
    }
    fingerprint = f"{payload['handle']}|{body[:300]}|{desc[:300]}"
    payload["id"] = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return payload


def parse_dump(xml_path: Path) -> list[dict]:
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        log(f"XML parse error on {xml_path}: {e}")
        return []
    tweets: list[dict] = []
    for outer in tree.iter("node"):
        if outer.get("resource-id") == ROW_OUTER_ID:
            try:
                parsed = parse_tweet(outer)
                if parsed is not None:
                    tweets.append(parsed)
            except Exception as e:
                log(f"parse_tweet failed: {e}")
    return tweets


def timeline_visible(xml_path: Path) -> bool:
    """Cheap check that we're on the timeline (vs. a detail view)."""
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return False
    return any(n.get("resource-id") == TIMELINE_LIST_ID for n in tree.iter("node"))


def _extract_detail_body(detail_xml: Path, truncated_body: str) -> tuple[str, str]:
    """Pull the full tweet body out of a detail-page UI dump.

    Returns ``(body, source)`` where source is a short tag describing which
    path matched (for diagnostic logging). Body is empty if nothing matched.

    Strategy order:
      1. Prefix-match — find the longest text in the dump that starts with
         the first 40 chars of the truncated body. Most reliable; survives
         X UI shuffles and picks up the focal tweet specifically.
      2. Resource-id match (tweet_text, then tweet_content_text). Only
         accept candidates strictly longer than the truncated body, which
         filters out unrelated tweet_text elements like the reply composer
         hint ("Post your reply").
    """
    try:
        tree = ET.parse(detail_xml)
    except ET.ParseError:
        return "", "parse_error"

    if truncated_body and len(truncated_body) >= 20:
        prefix = truncated_body[:40].strip()
        if prefix:
            candidates: list[str] = []
            for n in tree.iter("node"):
                text = n.get("text") or ""
                if text.startswith(prefix) and len(text) > len(truncated_body):
                    candidates.append(text)
            if candidates:
                return max(candidates, key=len), "prefix_match"

    min_len = max(len(truncated_body) + 1, 30)
    for body_id in DETAIL_BODY_IDS:
        short_id = body_id.split("/")[-1]
        for container in tree.iter("node"):
            if container.get("resource-id") != body_id:
                continue
            text = container.get("text") or ""
            if not text:
                for inner in container.iter("node"):
                    inner_text = inner.get("text") or ""
                    if inner_text:
                        text = inner_text
                        break
            if text and len(text) >= min_len:
                return text, short_id

    return "", "no_match"


def expand_truncated(tweet: dict, tmpdir: Path, debug_dir: Path | None) -> str | None:
    """Tap the tweet header to open its detail view, grab full body, press back.

    Returns the full body text on success, None on failure. On failure, the
    detail UI dump is preserved under debug_dir for inspection if provided.
    """
    target = tweet.get("header_bounds") or tweet.get("bounds")
    if not target:
        return None
    # Tap a bit right of header center; left side is avatar / display-name link,
    # both of which navigate to the user's profile instead of the tweet detail.
    cx = int(target[0] + 0.66 * (target[2] - target[0]))
    cy = (target[1] + target[3]) // 2

    log(f"  expanding @{tweet['handle']} via tap({cx},{cy})")
    tap(cx, cy)
    # Slightly longer initial wait; video tweets render slowly on the detail page.
    time.sleep(random.uniform(2.4, 3.4))

    detail_xml = tmpdir / "detail.xml"
    if not dump_ui(detail_xml):
        log("  expand: detail dump failed, returning to timeline")
        press_back()
        time.sleep(random.uniform(1.0, 1.6))
        return None

    full, source = _extract_detail_body(detail_xml, tweet["body"])
    if full:
        log(f"  expand: matched via {source}")

    press_back()
    time.sleep(random.uniform(1.2, 1.9))

    recovery_xml = tmpdir / "recovery.xml"
    if dump_ui(recovery_xml) and not timeline_visible(recovery_xml):
        log("  expand: timeline missing after back, relaunching X")
        ensure_twitter_foreground()

    if full and full != tweet["body"]:
        return full

    # Failure path: keep the detail dump for diagnosis.
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        fname = f"expand_fail_{tweet['handle']}_{tweet['id']}.xml"
        try:
            (debug_dir / fname).write_text(detail_xml.read_text())
            log(f"  expand failed; saved detail dump -> {fname}")
        except OSError as e:
            log(f"  expand failed; could not save detail dump: {e}")
    return None


def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scroll + capture the X timeline.")
    p.add_argument("--output-root", type=Path, default=Path("./twitter_captures"))
    p.add_argument("--max-tweets", type=int, default=50)
    p.add_argument("--max-pages", type=int, default=30)
    p.add_argument("--max-seconds", type=int, default=600)
    p.add_argument("--expand-rate", type=float, default=0.5,
                   help="Fraction of truncated tweets to drilldown-expand (0-1).")
    p.add_argument("--no-expand", action="store_true",
                   help="Skip show-more drilldown entirely.")
    p.add_argument("--empty-pages-to-stop", type=int, default=2)
    p.add_argument("--no-foreground-launch", action="store_true",
                   help="Skip launching X (assume already foreground).")
    p.add_argument("--keep-pages", action="store_true",
                   help="Keep per-page screenshots + UI dumps (default: only first + last).")
    p.add_argument("--include-video", action="store_true",
                   help="Include video tweets in output (default: skip them; videos "
                        "belong on the TikTok pipeline).")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    serial = device_serial()
    now = datetime.now(timezone.utc)
    day_dir = args.output_root.expanduser() / now.strftime("%Y-%m-%d")
    pages_dir = day_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    prefix = f"{serial}_{stamp}"
    manifest_path = day_dir / f"{prefix}_run.json"

    debug_dir = day_dir / "debug"
    log(f"device={serial}  output={day_dir}")
    log(f"limits: max_tweets={args.max_tweets} max_pages={args.max_pages} "
        f"max_seconds={args.max_seconds} expand_rate={args.expand_rate}")

    if not args.no_foreground_launch:
        ensure_twitter_foreground()

    seen: dict[str, dict] = {}
    page_files: list[dict] = []
    expansion_attempts = 0
    expansion_successes = 0
    video_skipped = 0
    started_at = time.monotonic()
    empty_pages = 0
    page_num = 0

    with tempfile.TemporaryDirectory(prefix="capture_twitter_") as tmpdirname:
        tmpdir = Path(tmpdirname)

        while True:
            elapsed = time.monotonic() - started_at
            if elapsed >= args.max_seconds:
                log(f"stop: max_seconds reached ({elapsed:.0f}s)")
                break
            if page_num >= args.max_pages:
                log(f"stop: max_pages reached ({page_num})")
                break
            if len(seen) >= args.max_tweets:
                log(f"stop: max_tweets reached ({len(seen)})")
                break

            page_num += 1
            page_tag = f"page{page_num:03d}"
            png_path = pages_dir / f"{prefix}_{page_tag}_screen.png"
            xml_path = pages_dir / f"{prefix}_{page_tag}_ui.xml"

            ok_xml = dump_ui(xml_path)
            ok_png = screencap(png_path)
            if not ok_xml:
                log(f"page {page_num}: UI dump failed, skipping")
                empty_pages += 1
                if empty_pages >= args.empty_pages_to_stop:
                    log("stop: too many failed pages")
                    break
                time.sleep(2.0)
                continue

            page_tweets = parse_dump(xml_path)
            new_in_page = 0
            page_video_skipped = 0
            for t in page_tweets:
                if t["id"] in seen:
                    continue
                if t["has_video"] and not args.include_video:
                    video_skipped += 1
                    page_video_skipped += 1
                    continue
                if (
                    t["truncated"]
                    and not args.no_expand
                    and random.random() < args.expand_rate
                ):
                    expansion_attempts += 1
                    full = expand_truncated(t, tmpdir, debug_dir)
                    if full:
                        t["body"] = full
                        t["truncated"] = False
                        t["expanded"] = True
                        expansion_successes += 1
                seen[t["id"]] = t
                new_in_page += 1

            log(f"page {page_num}: parsed {len(page_tweets)}, "
                f"+{new_in_page} new, {page_video_skipped} video skipped "
                f"(total {len(seen)})")

            page_files.append({
                "page": page_num,
                "screen_png": str(png_path.relative_to(day_dir)) if ok_png else None,
                "ui_xml": str(xml_path.relative_to(day_dir)),
                "tweets_visible": len(page_tweets),
                "new_tweets": new_in_page,
            })

            if new_in_page == 0:
                empty_pages += 1
                if empty_pages >= args.empty_pages_to_stop:
                    log(f"stop: {empty_pages} consecutive pages with no new tweets")
                    break
            else:
                empty_pages = 0

            # Page-level cleanup of intermediate files (keep first + last only by default).
            if (
                not args.keep_pages
                and page_num != 1
                and len(seen) < args.max_tweets
            ):
                # Defer removal of "last" page until after the loop ends; here we
                # only delete the *previous* page's files if they aren't page 1.
                prev_tag = f"page{page_num - 1:03d}"
                for stale in pages_dir.glob(f"{prefix}_{prev_tag}_*"):
                    if "page001" not in stale.name:
                        stale.unlink(missing_ok=True)

            # Scroll + jittered sleep.
            swipe_up()
            time.sleep(random.uniform(1.5, 3.2))
            if page_num % 8 == 0:
                pause = random.uniform(8.0, 16.0)
                log(f"  long pause {pause:.1f}s (humanlike cadence)")
                time.sleep(pause)

    elapsed_total = time.monotonic() - started_at
    manifest = {
        "captured_at": now.isoformat(),
        "device_serial": serial,
        "source_app": PKG,
        "args": vars(args) | {"output_root": str(args.output_root)},
        "pages_captured": page_num,
        "tweets_captured": len(seen),
        "video_tweets_skipped": video_skipped,
        "expansion_attempts": expansion_attempts,
        "expansion_successes": expansion_successes,
        "elapsed_seconds": round(elapsed_total, 1),
        "page_files": page_files,
        "tweets": list(seen.values()),
    }
    atomic_write_json(manifest_path, manifest)
    log(
        f"done: {len(seen)} tweets, {page_num} pages, "
        f"{video_skipped} video skipped, "
        f"expand {expansion_successes}/{expansion_attempts}, "
        f"{elapsed_total:.0f}s -> {manifest_path}"
    )
    for t in list(seen.values())[:10]:
        flag = "+" if t["expanded"] else ("…" if t["truncated"] else " ")
        body = (t["body"] or "<media-only>").replace("\n", " ")[:90]
        print(f"  {flag} @{t['handle']}: {body}")


if __name__ == "__main__":
    main()
