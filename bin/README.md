# 🌌 COSMIC System Extension (sysext) — `bin/` Scripts Guide

This directory contains the three scripts that form the **sysext delivery workflow** for Debian COSMIC. Together they let you install, activate, deactivate, and keep COSMIC up-to-date without touching your host's `/usr` tree.

---

## Overview

| Script | Purpose |
|--------|---------|
| [`cosmic-update`](#cosmic-update) | Pull the latest COSMIC OCI images from GHCR and stage them under `/var/lib/extensions/` |
| [`cosmic-toggle`](#cosmic-toggle) | Merge (activate) or unmerge (deactivate) the extension, with ABI-safety checks |
| [`generate-cosmic-canary.sh`](#generate-cosmic-canarysh) | Scan the staged COSMIC binaries and build the `cosmic-canary` ABI-safety package |

The recommended first-time workflow is:

```
cosmic-update  →  generate-cosmic-canary.sh  →  cosmic-toggle on
```

---

## Prerequisites

- **Debian Testing or Sid** host
- **systemd ≥ 248** (provides `systemd-sysext`)
- **Docker** (used by `cosmic-update` to extract OCI image layers)
- **equivs** (`sudo apt install equivs`) — required by `generate-cosmic-canary.sh`

---

## `cosmic-update`

Downloads the COSMIC sysext OCI image(s) from the GitHub Container Registry and extracts them into `/var/lib/extensions/`. After the update the host `/usr` is left in its **pristine, unmerged state**; use `cosmic-toggle on` when you are ready to activate.

### Usage

```bash
# Update the COSMIC stack (compositor, panel, settings, …)
sudo cosmic-update

# Pin to a specific image tag instead of 'latest'
sudo cosmic-update v1.0.11
```

### What it does

1. **Unmerges** any active extension so that `/usr` is writable.
2. Pulls the image(s) listed in `BUCKETS` from `ghcr.io/rickysarraf/`.
3. Creates (or replaces) `/var/lib/extensions/<name>/usr` with the OCI layer content.
4. **Sanitises** the extracted tree — removes host-critical binaries (`env`, `sh`, `bash`, `ldconfig`) and artefacts that must not shadow the host.
5. Leaves the system **unmerged**. You must run `cosmic-toggle on` (and rebuild the canary if you haven't) before using the desktop.

### Extension directories

| Image bucket | Staged path |
|---|---|
| `debian-testing-cosmic-sysext` | `/var/lib/extensions/cosmic/` |

---

## `generate-cosmic-canary.sh`

Scans every ELF binary inside the staged COSMIC tree, resolves their runtime library dependencies to host Debian packages, and produces a `cosmic-canary` Debian package that **pins** those exact library versions. Installing the canary makes `apt` alert you before any host upgrade that would break ABI compatibility with the active extension.

### Usage

```bash
# Full workflow: generate control file + build the .deb (defaults to /var/lib/extensions/cosmic/usr)
./bin/generate-cosmic-canary.sh

# Specify a different staged tree
./bin/generate-cosmic-canary.sh /var/lib/extensions/cosmic/usr

# Generate only the equivs control file (skip the build step)
./bin/generate-cosmic-canary.sh --control-only

# Output only the raw comma-separated dependency string (useful for scripting)
./bin/generate-cosmic-canary.sh --raw
```

### Tiered dependency model

| Zone | Dependency operator | Libraries covered |
|---|---|---|
| **Strict** | `= <exact-version>` | Everything not in the relaxed list |
| **Relaxed** | `>= <version>` | `libc6`, `libgcc-s1`, `libstdc++6`, `libwayland*`, `libdbus*`, `libpam*`, `libglib*`, `libasound*`, `libssl*`, `libx11*` |

### First-time setup (after `cosmic-update`)

```bash
# 1. Build and install the canary
./bin/generate-cosmic-canary.sh
sudo apt install ./cosmic-canary_*.deb

# 2. Activate the extension
cosmic-toggle on
```

### Rebuilding after an extension update

Every time you run `cosmic-update` you should rebuild and reinstall the canary so the pins reflect the new binary set:

```bash
cosmic-toggle off          # unmerge first
cosmic-update              # pull latest images
./bin/generate-cosmic-canary.sh
sudo apt install ./cosmic-canary_*.deb
cosmic-toggle on           # re-activate
```

---

## `cosmic-toggle`

Merges or unmerges the COSMIC system extension. When turning the extension **on**, the script first verifies that the `cosmic-canary` package is installed and that no unmet dependencies exist — this prevents activating an extension whose ABI is incompatible with the current host libraries.

### Usage

```bash
# Check whether the extension is currently active
cosmic-toggle status

# Activate the extension (requires the canary to be installed and healthy)
cosmic-toggle on

# Deactivate the extension (leaves host /usr pristine)
cosmic-toggle off
```

### ABI safety check (on activation)

Before merging, `cosmic-toggle on` runs two checks:

1. **Canary installed?** — If `cosmic-canary` is not found via `dpkg -l`, the command aborts.
2. **No unmet dependencies?** — Runs `apt-get check`. If any strict-pinned library has drifted (e.g. a Mesa upgrade landed), the command aborts with a warning telling you to rebuild the extension or the canary.

### `status` output

```
🟢 STATUS: COSMIC Extension is ACTIVE.
--- Details ---
…systemd-sysext status output…
```

---

## End-to-end example

### First-time installation

```bash
# 1. Pull the latest COSMIC images
sudo cosmic-update

# 2. Build and install the ABI-safety canary
./bin/generate-cosmic-canary.sh
sudo apt install ./cosmic-canary_*.deb

# 3. Activate COSMIC
cosmic-toggle on

# 4. Restart the display manager (or log out and back in)
sudo systemctl restart gdm
```

### Applying an update

```bash
cosmic-toggle off
sudo cosmic-update
./bin/generate-cosmic-canary.sh
sudo apt install ./cosmic-canary_*.deb
cosmic-toggle on
sudo systemctl restart gdm
```

### Checking current state

```bash
cosmic-toggle status
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `cosmic-toggle on` aborts with "canary not installed" | `cosmic-canary` has never been built/installed | Run `generate-cosmic-canary.sh` then `apt install` the resulting `.deb` |
| `cosmic-toggle on` aborts with "ABI drift detected" | A host library was upgraded past the canary's pinned version | Run `cosmic-update` and rebuild the canary |
| Black screen / segfault after merge | ABI mismatch slipped through (canary was stale) | Run `cosmic-toggle off`, rebuild canary, reinstall, then `cosmic-toggle on` |
| `docker pull` fails in `cosmic-update` | Network issue or GHCR rate-limit | Retry; ensure Docker is logged in if needed |
| `equivs-build` not found | `equivs` package missing | `sudo apt install equivs` |
