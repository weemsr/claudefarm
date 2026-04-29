#!/usr/bin/env bash
# Idempotent bootstrap for the target Mac Mini (the production host, NOT your dev machine).
# Re-runnable. Each step checks state before acting.
#
# Usage: ./scripts/bootstrap_host.sh
# Prerequisites: macOS on Apple Silicon, admin user, Homebrew NOT required (installed below).

set -euo pipefail

# Colors for readability
G=$'\033[0;32m'; Y=$'\033[0;33m'; R=$'\033[0;31m'; N=$'\033[0m'
log() { echo "${G}==>${N} $*"; }
warn() { echo "${Y}!! ${N}$*"; }
err() { echo "${R}XX${N} $*" >&2; }

# Sanity: are we on the target Mac Mini, or the dev box?
read -r -p "Is THIS machine the production Mac Mini host? [y/N] " yn
if [[ ! "$yn" =~ ^[Yy]$ ]]; then
  err "Abort. Run this only on the production host."
  exit 1
fi

# --- 1. Homebrew ---
if ! command -v brew >/dev/null 2>&1; then
  log "Installing Homebrew"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Apple Silicon brew prefix
  eval "$(/opt/homebrew/bin/brew shellenv)"
else
  log "Homebrew already present"
fi

# --- 2. Core packages ---
BREW_PKGS=(redis ffmpeg uv pandoc rsync tailscale)
BREW_CASKS=(android-platform-tools scrcpy)

for pkg in "${BREW_PKGS[@]}"; do
  if brew list --formula "$pkg" >/dev/null 2>&1; then
    log "$pkg already installed"
  else
    log "Installing $pkg"
    brew install "$pkg"
  fi
done

for cask in "${BREW_CASKS[@]}"; do
  if brew list --cask "$cask" >/dev/null 2>&1; then
    log "$cask already installed"
  else
    log "Installing $cask"
    brew install --cask "$cask"
  fi
done

# --- 3. Prevent sleep (host must stay awake while devices capture) ---
if pmset -g | grep -q "SleepDisabled.*1"; then
  log "Sleep already disabled"
else
  log "Disabling sleep (requires sudo)"
  sudo pmset -a disablesleep 1
  sudo pmset -a sleep 0 displaysleep 0
fi

# --- 4. Redis as a launchd service (user scope, not system) ---
if brew services list | grep -q '^redis.*started'; then
  log "Redis already running"
else
  log "Starting redis via brew services"
  brew services start redis
fi

# --- 5. FARM_ROOT on external SSD ---
DEFAULT_FARM_ROOT="/Volumes/FarmSSD/farm_data"
read -r -p "Path to FARM_ROOT on external SSD [${DEFAULT_FARM_ROOT}]: " farm_root
farm_root="${farm_root:-$DEFAULT_FARM_ROOT}"

parent="$(dirname "$farm_root")"
if [[ ! -d "$parent" ]]; then
  err "Parent $parent does not exist. Mount the external SSD first."
  exit 1
fi

mkdir -p "$farm_root"/{raw/tiktok,raw/twitter,processed/transcripts,processed/ocr,processed/frames,db,exports/summaries}
log "FARM_ROOT ready at $farm_root"

# --- 6. Tailscale ---
if tailscale status >/dev/null 2>&1; then
  log "Tailscale already authenticated"
else
  warn "Run: sudo tailscale up    (interactive auth needed)"
fi

# --- 7. Summary ---
cat <<EOF

${G}Bootstrap complete.${N}

Next:
  1. cd <repo>/farm && uv sync
  2. cp .env.example .env   and fill in API keys + proxy creds + device serials
  3. Export FARM_ROOT in your shell:  echo 'export FARM_ROOT=$farm_root' >> ~/.zshrc
  4. Plug in phones, run phone_onboarding.md per device.
  5. Schedule nightly rsync via launchd (see scripts/rsync_backup.sh when it exists).
EOF
