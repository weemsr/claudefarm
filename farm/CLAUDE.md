**Phone Farm Scraping Project**

*Claude Code Context Document*

*Drop this into the repo root as CLAUDE.md (or paste as context). It
captures the full architecture and every decision already made so you
don’t waste turns re-litigating them. Edit the “Current State” and
“Immediate Next Steps” sections to reflect what’s actually built.*

# Project Goal

Build a small-scale Android phone farm for scraping TikTok and Twitter,
preprocess captured media locally (free), and synthesize insights via a
cheap LLM API. Target scale: **3 physical devices running 4–5
hours/day** (1 TikTok, 2 Twitter). The architecture should cleanly scale
to 10–30 devices later without rewriting the pipeline.

# Hardware

## Phones

- **Preferred:** Pixel 3a / 3a XL (~\$50–90 used) — trivial bootloader
  unlock, stock AOSP, best uiautomator2 behavior, clean ADB.

- **Acceptable:** Pixel 4a non-5G (~\$90–150) — same advantages,
  slightly faster.

- **Budget alternative:** Samsung Galaxy A13/A14 (~\$40–80) — needs ADB
  doze/battery-optimization workarounds but fine.

- **Avoid:** Xiaomi/Redmi/POCO (MIUI kills background processes),
  anything pre-Android 9 (TikTok/X won’t install), \<2 GB RAM devices.

## Host & Infrastructure

- **Host machine:** Mac Mini M2/M4 or small Linux mini-PC. 16 GB RAM
  minimum. Wired Gigabit Ethernet.

- **USB hub:** Powered USB 3.0 with its own brick (Anker/Sabrent
  10-port).

- **Cables:** Short quality USB-C (Anker PowerLine 1–3 ft). Cheap long
  cables cause ADB disconnects.

- **Per-port power control (optional upgrade):** Yepkit YKUSH3 (~\$250)
  for scriptable cycling of hung devices.

- **Primary storage:** External NVMe SSD over USB 3.2 Gen 2 or
  Thunderbolt. Samsung T7 Shield 2 TB or DIY NVMe-in-enclosure. Not
  spinning disk — too many small random I/O ops.

- **Backup drive:** Second external drive (can be slower/cheaper) for
  nightly rsync.

- **Physical:** Acrylic phone farm rack + one 120 mm fan for airflow.

# Software Stack

| **Layer** | **Choice** | **Why** |
|----|----|----|
| Language | Python 3.11+ | Ecosystem fit for uiautomator2, Whisper, PaddleOCR |
| Device automation | uiautomator2, adbutils | Fastest selector path for Android |
| Screen mirror | scrcpy | Free, reliable, handles dozens of devices |
| Optional UI | DeviceFarmer (Docker) | Web dashboard for device status + remote takeover |
| Audio → text | faster-whisper or whisper.cpp (medium) | Free, real-time on Apple Silicon |
| OCR | PaddleOCR (preferred) or Tesseract | PaddleOCR handles stylized fonts better |
| Video frames | ffmpeg + imagehash | Extract + dedupe via perceptual hash |
| Text dedup | datasketch (MinHash) | Near-duplicate tweet detection |
| Queue | Redis + RQ | Simpler than Celery at this scale |
| Database | DuckDB (preferred) or SQLite | Analytical queries on scraped data |
| LLM synthesis | MiniMax M2.7 via API | \$0.30 / \$1.20 per M tokens, 205K context |
| LLM fallback | Claude Haiku 4.5 | Second-opinion runs, English nuance |
| Optional local LLM | Qwen 2.5 7B/14B (Ollama / MLX) | Free per-item filtering on the Mac Mini |
| Config | pydantic-settings + .env | Secrets never in git |
| Logging | structlog → JSON → stdout | Captured by systemd/launchd |
| Tests | pytest | Smoke tests per pipeline stage |

# Architecture Principles

1.  **Preprocess locally, always.** Whisper, OCR, and ffmpeg are free —
    use them before any paid LLM call. Caption + audio transcript + top
    comments + on-screen OCR covers 90%+ of TikTok content without ever
    sending pixels to a vision model.

2.  **Two-stage LLM pipeline.** Cheap/local model for per-item
    classification and filtering → MiniMax M2.7 for synthesis on the
    filtered subset only. Kills 50–70% of calls before they cost
    anything.

3.  **Partitioned storage.** All artifacts under YYYY-MM-DD/ directories
    so old data can be archived or purged by date.

4.  **Atomic writes.** Write to \*.tmp, then os.rename() to final name.
    Prevents partial-write corruption if the external drive blips.

5.  **One job per service.** Capture, preprocess, enrich, synthesize —
    separate processes communicating via Redis. No service can block
    another.

6.  **Idempotent stages.** Every stage can be re-run on existing data
    without duplicating work. Use content hashes as primary keys.

7.  **Secrets in .env.** API keys, proxy credentials, device IDs never
    committed. .env.example is committed; .env is gitignored.

8.  **No ADB over WAN.** Host + devices stay on the tailnet or local
    network only.

# Storage Layout

Base path on the external SSD, configurable via FARM_ROOT env var.

\$FARM_ROOT/

├── raw/

│ ├── tiktok/YYYY-MM-DD/

│ │ ├── {device_id}\_{timestamp}\_video.mp4

│ │ ├── {device_id}\_{timestamp}\_meta.json \# caption, author, counts

│ │ └── {device_id}\_{timestamp}\_comments.json

│ └── twitter/YYYY-MM-DD/

│ ├── {device_id}\_{timestamp}\_screenshot.png

│ └── {device_id}\_{timestamp}\_meta.json \# tweet text, author, thread
ctx

├── processed/

│ ├── transcripts/YYYY-MM-DD/ \# Whisper .json (timestamps) + .txt

│ ├── ocr/YYYY-MM-DD/ \# PaddleOCR .json with bboxes

│ └── frames/YYYY-MM-DD/ \# sampled + deduped .jpg

├── db/

│ └── farm.duckdb

└── exports/

└── summaries/YYYY-MM-DD/ \# LLM syntheses, .md + .json

## External Drive Discipline

- Format **APFS** (Mac-only) or **ExFAT** (cross-platform). Never NTFS
  on Mac.

- Disable system sleep on the host (pmset disablesleep 1 on Mac) to
  avoid mid-write unmounts.

- **Storage budget:** ~6–7 GB/day at full fidelity, ~2–3 GB/day if raw
  video discarded after transcript extraction. 2 TB drive ≈ 9 months
  full capture; 4 TB if the price delta is small.

- **Nightly rsync** to secondary drive via cron/launchd.

- **Cloud backup** (Backblaze B2 or Cloudflare R2) for db/ and exports/
  only — raw media is reproducible, enriched data is not.

# LLM Cost Model & Budget

**Target: under \$30/month** at 3 devices × 5 hours/day.

### Estimated Daily Volume

- TikTok device: ~1,000 videos × ~900 tokens (meta + Whisper transcript)
  ≈ 900K tokens

- Twitter devices: ~4,000 unique tweets × ~200 tokens (with thread
  context) ≈ 800K tokens

- **Total input:** ~1.7–2M tokens/day

### Expected Cost on MiniMax M2.7

(\$0.30 in / \$1.20 out per M tokens)

| **Pipeline**                           | **Input/day** | **Daily** | **Monthly** |
|----------------------------------------|---------------|-----------|-------------|
| Text-only (captions, tweets, comments) | 2M            | ~\$0.62   | ~\$19       |
| \+ Whisper transcripts (local, free)   | 3M            | ~\$0.92   | ~\$28       |
| \+ Sampled vision frames               | 7.5M          | ~\$2.30   | ~\$68       |

### Optimization Levers

- **Prompt caching** — M2.7 supports automatic caching. Cache the system
  prompt and extraction schema across calls.

- **Local Qwen 2.5 7B for triage** — classify/filter before the M2.7
  call.

- **Batch processing** for non-real-time synthesis if the provider
  supports it.

- **Skip vision unless necessary** — transcript + OCR + comments is
  usually enough.

# Network & Proxies

- Host on **wired Ethernet**.

- Phones on a **dedicated WiFi SSID**, VLAN-isolated from the main
  network.

- **Residential proxies per device:**

  - Phase 1: per-device proxy config on-phone (Drony, or
    Shadowsocks/ProxyDroid on rooted devices).

  - Phase 2: router-level policy routing by MAC address (MikroTik hAP or
    pfSense/OPNsense).

- **Tailscale** for remote host management. ADB never exposed to WAN.

# Device Management

- Bootloader unlocked where possible; minimum Android 10.

- Disable battery optimization / doze for automation-critical apps:

adb shell dumpsys deviceidle whitelist +\<package\>

adb shell cmd appops set \<package\> RUN_IN_BACKGROUND allow

- **Health-check loop** (every 60s): adb shell echo alive. After 3
  consecutive failures, cycle the USB port (YKUSH3 if present, else
  log + alert via pushover/ntfy/Slack webhook).

- **Battery swelling mitigation:** cap charge at 60–80% via Magisk +
  AccA, or remove batteries and run on USB power only (Pixels are
  serviceable; Samsungs less so).

# Data Safety & Compliance

- All scraped content is **public data**.

- **Never** include credentials, proxy auth, or account PII in LLM
  prompts.

- MiniMax is a Chinese provider; data sent to their API is subject to
  PRC regulations. Don’t send anything you wouldn’t want on a Chinese
  server. Scraped public posts: fine. Anything secret: route to Claude
  or process locally.

- Respect TikTok/X ToS at your own risk; treat this as a personal
  research project.

# Service Layout

One Python package per service, each runnable independently:

farm/

├── farm/

│ ├── capture/ \# uiautomator2 scripts, one module per app (tiktok,
twitter)

│ ├── preprocess/ \# Whisper, PaddleOCR, ffmpeg workers

│ ├── enrich/ \# LLM classification + structured extraction

│ ├── synthesize/ \# Scheduled synthesis jobs

│ ├── common/ \# pydantic models, DB schema, config, logging

│ └── ops/ \# health checks, USB port cycling, alerting

├── scripts/ \# one-shot scripts (backfills, rsync, drive setup)

├── tests/

├── .env.example

├── pyproject.toml

└── CLAUDE.md \# this file

Services communicate via Redis + RQ. Each stage consumes from its input
queue, writes artifacts to disk + DB, enqueues the next stage.

# Coding Conventions

- **Type-annotated Python**, mypy in strict-ish mode.

- pydantic models for every data structure passed between services.

- **Structured logging** with structlog — JSON to stdout, captured by
  systemd/launchd.

- **Atomic file writes** via a small utils.atomic_write() helper.

- **Retry with exponential backoff** on every network call (LLM, proxy,
  ADB).

- **Content hashes as primary keys** (SHA256 of tweet text / video ID)
  so re-runs are idempotent.

- One pytest smoke test per pipeline stage with a committed fixture
  record.

# Current State

**TODO: fill this in.** Example entries:

- \[x\] uiautomator2 TikTok “For You” scroll + video download
  implemented

- \[ \] Twitter timeline capture in progress

- \[ \] No preprocessing pipeline yet

- \[ \] DB schema not finalized

- \[ \] Running on a single Pixel 3a for testing; 2 more phones on order

# Immediate Next Steps

9.  Finalize capture output schema (pydantic models for TikTok + Twitter
    records).

10. Stand up the preprocessing service: Whisper + PaddleOCR + ffmpeg
    workers watching raw/ for new files.

11. Define DuckDB schema for enriched records; write a migration runner.

12. Wire Redis + RQ queue between capture → preprocess → enrich.

13. Implement MiniMax M2.7 client with automatic caching and
    retry/backoff.

14. Build per-device health-check loop with USB port cycling.

15. Write the rsync backup script; schedule via cron/launchd.

16. Add structured logging across all services with run IDs.

# Context to Ask Me About

Ask me about any of these when relevant — don’t assume:

- Exact phone models purchased and Android versions running.

- Existing code structure and which capture flows are already
  implemented.

- Proxy provider and current residential IP setup.

- Deployment host (Mac Mini specs / OS version) and whether it’s the
  final host.

- Whether a Magisk/root environment is set up on the devices yet.

# Things Not to Suggest

Decisions already made — don’t re-litigate unless I explicitly ask:

- **✗** “Have you considered using cloud phones / emulators?” — No, this
  project is physical-device.

- **✗** “Use Celery instead of RQ.” — RQ is fine at this scale.

- **✗** “Use Postgres from day one.” — DuckDB/SQLite first; upgrade if
  needed.

- **✗** “Default to Claude Sonnet for everything.” — MiniMax M2.7 is the
  synthesis model by design.

- **✗** “Store data on the internal SSD.” — External SSD is intentional.

- **✗** “Use Appium.” — uiautomator2 is faster and already in use.
