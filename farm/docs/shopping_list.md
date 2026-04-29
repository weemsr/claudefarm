# Shopping List

Prioritized by lead time + blocking-ness. Buy Tier 1 before phones arrive; Tier 2 can follow.

Prices are approximate as of 2026 — verify before ordering. All links omitted on purpose; search the SKU on Amazon / Newegg / B&H.

---

## Tier 1 — Blocks first capture

| Item | SKU / Spec | Qty | ~Price | Why |
|---|---|---|---|---|
| Host: Mac Mini | M2 or M4, 16 GB RAM min, 256 GB internal (data goes external) | 1 | $600–800 | Apple Silicon required for fast Whisper/MLX. User says "different Mac Mini" — confirm specs before relying on it. |
| External SSD (primary) | Samsung T7 Shield 2 TB, USB 3.2 Gen 2 | 1 | $140 | APFS-formatted. 2 TB ≈ 9 months full-fidelity capture. Step up to 4 TB if price delta < $80. |
| Powered USB hub | Anker 10-port USB 3.0 with its own 60W brick | 1 | $40 | Cheap hubs brownout under 3+ phones charging. Dedicated brick is non-negotiable. |
| USB-C data cables | Anker PowerLine II, 3 ft, USB-A to USB-C (match hub port) | 5 | $40 | 3 for phones, 2 spares. Short + quality = zero ADB disconnects. Avoid generic Amazon basics at length > 3ft. |
| Ethernet cable | Cat 6, 10 ft | 1 | $10 | Host on wired. |

Subtotal Tier 1 (excluding Mac Mini if already owned): **~$230**

## Tier 2 — Needed by the time you scale past 2 devices

| Item | SKU / Spec | Qty | ~Price | Why |
|---|---|---|---|---|
| External SSD (backup) | Any 2 TB USB SSD, can be slower/cheaper | 1 | $90 | Nightly rsync target. Separate physical device. |
| Acrylic phone farm rack | 6–10 slot, search "phone farm rack acrylic" | 1 | $40–80 | Keeps phones vertical + ventilated. |
| 120 mm fan + USB adapter | Noctua NF-P12 or similar + USB-powered controller | 1 | $25 | Points at the rack. Phones at 100% CPU for hours get warm. |
| WiFi router (scraping SSID) | Any dual-band with VLAN support; MikroTik hAP ax² if you want per-MAC policy routing | 1 | $70–150 | Isolate phone traffic. Also where Phase-2 proxy routing lives. |

Subtotal Tier 2: **~$230–350**

## Tier 3 — Quality-of-life upgrades

| Item | SKU / Spec | Qty | ~Price | Why |
|---|---|---|---|---|
| Yepkit YKUSH3 | 3-port scriptable USB power switch | 1 | $250 | Automated port cycling when a device hangs. Skip until you've had 2+ manual un-plug events. |
| UPS | CyberPower 600VA | 1 | $90 | Blips mid-write corrupt DuckDB. APFS is more forgiving, but still. |
| Second host (Linux mini-PC) | Beelink / GMKtec N100, 16 GB RAM | 1 | $250 | Only if you move beyond 10 devices and the Mac Mini becomes the bottleneck. |

---

## Residential proxies — subscription, not hardware

**The doc's $30/mo budget is LLM-only. Add proxies:**

| Provider | Pricing model | Realistic cost at 3 devices × 5 hr/day |
|---|---|---|
| Bright Data | $8.40/GB (pay-as-you-go) | $60–150/mo depending on video bandwidth |
| Smartproxy | $7/GB or $50/mo for 8 GB plans | $50–120/mo |
| IPRoyal | $7/GB (royal residential) | $50–120/mo |
| Oxylabs | $8/GB enterprise | $60–150/mo |

**Decision points:**
- Do you actually need residential? Datacenter proxies ($10–30/mo) work for X/Twitter text scraping; TikTok video fetches typically trigger harder on datacenter IPs.
- Rotating vs sticky session? You want **sticky sessions per device** (same IP for the whole capture run) to avoid login loops.
- Phase 1 = per-device proxy app on-phone. Phase 2 = router-level MAC-based routing (cheaper to manage, not cheaper in $). Don't bother with Phase 2 until you have 5+ devices.

**Before committing:** buy the smallest plan ($10–20 trial) on one provider, verify their IPs aren't already flagged by TikTok/X, then scale. Do NOT prepay annually — residential IP quality changes.

---

## What NOT to buy yet

- **Cloud phones / emulator services** — doc explicitly excludes; physical only.
- **More than 3 phones** — prove the pipeline on 2 first. Scaling is a separate phase.
- **Magisk modules** beyond AccA — each root module is a compatibility risk.
- **GPU** — faster-whisper + Apple Silicon's Neural Engine handle audio; no NVIDIA needed at this scale.
