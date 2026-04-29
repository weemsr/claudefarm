# Phone Onboarding Checklist

Per-phone checklist from factory-unbox → ADB-authorized → ready for automation. Run through this once per device. Track completion in `docs/device_registry.md` (create when first phone arrives).

---

## 0. Before the phone arrives

- [ ] Decide the phone's role: `tiktok` or `twitter`. Write it on a sticker for the back of the phone.
- [ ] Note the IMEI / serial from the receipt (for inventory, not needed for ADB).

## 1. First boot & setup

- [ ] Skip sign-in on setup wizard if possible ("Set up later"). You don't want a Google account on a scraping device unless required.
- [ ] Connect to the scraping WiFi SSID (not the main network). VLAN isolation happens at the router.
- [ ] Update to latest Android (Settings → System → System update). Takes 1–2 reboots.

## 2. Enable developer options + USB debugging

- [ ] Settings → About phone → tap **Build number** 7 times until "You are now a developer" appears.
- [ ] Settings → System → Developer options:
  - [ ] **USB debugging** → ON
  - [ ] **OEM unlocking** → ON (required for bootloader unlock — if this toggle is greyed out, the phone is carrier-locked and the next step will fail)
  - [ ] **Stay awake while charging** → ON (prevents screen sleep during captures)
  - [ ] **Don't lock screen while charging** → ON (if present)

## 3. Bootloader unlock gate (do this BEFORE committing to the device)

On the host Mac Mini:

```bash
adb reboot bootloader
# phone reboots into fastboot
fastboot flashing get_unlock_ability
```

- Returns `1` → proceed to unlock.
- Returns `0` → **STOP**. Carrier-locked (common on Verizon Pixel 6). You cannot root this device, so Magisk + AccA battery capping is off the table. Capture still works without root, but the long-running health story is degraded. Decision point: keep as no-root capture-only, or return the phone.

If `1`, unlock:

```bash
fastboot flashing unlock
# phone shows a confirmation screen — use volume keys to select "Unlock the bootloader", press power
# this WIPES the device — you'll redo steps 1–2 after it reboots
fastboot reboot
```

- [ ] After wipe + reboot, redo steps 1–2 (dev options, USB debugging, OEM unlocking).
- [ ] Confirm bootloader is unlocked: boot screen shows a warning banner at boot time.

## 4. ADB authorization

On the host Mac Mini:

```bash
adb devices
# expected: <serial>  unauthorized   (on first connect)
# phone shows a "Allow USB debugging?" dialog — check "Always allow from this computer", tap Allow
adb devices
# expected: <serial>  device
```

- [ ] Record the serial in `.env` under the right key (`DEVICE_PIXEL_6=...` or `DEVICE_PIXEL_4A=...`).

## 5. Battery optimization / doze disables (per target app)

Once TikTok / X is installed (step 6), whitelist it so Android doesn't kill it during long captures:

```bash
adb shell dumpsys deviceidle whitelist +com.zhiliaoapp.musically   # TikTok US
# or
adb shell dumpsys deviceidle whitelist +com.twitter.android         # X/Twitter
adb shell cmd appops set <package> RUN_IN_BACKGROUND allow
```

- [ ] Whitelisted the capture target app.
- [ ] Disabled auto-brightness (Settings → Display) — steady brightness helps OCR consistency.
- [ ] Disabled screen rotation (Quick Settings) — lock to portrait.
- [ ] Disabled notifications for non-capture apps (they overlay UI and break selectors).

## 6. Install target apps

- [ ] TikTok (from Play Store, or sideload the region-specific APK if using a proxy for a different geo).
- [ ] X / Twitter (from Play Store).
- [ ] Walk through each app's initial setup: accept permissions, skip signup if scraping public feeds is the goal. Some flows require a throwaway account — decide per-device.

## 7. Magisk + AccA (OPTIONAL, only if bootloader unlocked successfully)

Skip this section if step 3 returned `0`.

- [ ] Flash Magisk per the official guide for the specific Pixel model.
- [ ] Install AccA from F-Droid.
- [ ] Configure AccA: charge cap 80%, discharge floor 60%. Prevents battery swelling during 24/7 tethered operation.

## 8. Proxy config (per device)

Phase 1 (on-device):

- [ ] Install Drony (non-root) or ProxyDroid (root-only).
- [ ] Configure the residential proxy endpoint for this device's role (different IP per phone).
- [ ] Verify: visit `https://api.ipify.org` in Chrome — IP should match the proxy, not your home WAN.

Phase 2 (router-level, later): handled at the MikroTik / pfSense by MAC address — no on-phone config.

## 9. Smoke test

From the host:

```bash
adb -s <serial> shell echo alive
adb -s <serial> shell dumpsys battery | grep level
scrcpy -s <serial>        # should mirror the screen
```

- [ ] All three succeed.
- [ ] Launch TikTok / X from the scrcpy session, scroll manually, confirm app is logged in (or logged out, per plan).
- [ ] Record completion date + any quirks in `docs/device_registry.md`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `adb devices` shows `unauthorized` forever | Didn't tap "Allow" on phone | Unplug/replug, watch screen, tap Allow |
| `adb devices` shows nothing | Cable is charge-only | Swap for data cable (Anker PowerLine); short cables preferred |
| `fastboot flashing unlock` says "not allowed" | OEM unlocking toggle off | Re-enable in Developer options, reboot to bootloader |
| Phone sleeps mid-capture | "Stay awake" off, or doze re-enabled | Re-run battery whitelist; verify "Stay awake while charging" |
| TikTok detects automation | uiautomator2's `atx-agent` signature | Known risk; mitigate with human-like delays, minimize root artifacts, rotate IP |
