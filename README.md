# <img src="https://www.debian.org/logos/openlogo-nd-100.png" height="36"> 🌌 Debian COSMIC

[![Debian COSMIC - Build Packages](https://github.com/rickysarraf/debian-cosmic/actions/workflows/build-packages.yml/badge.svg)](https://github.com/rickysarraf/debian-cosmic/actions/workflows/build-packages.yml)

Welcome to the standalone **Debian COSMIC** project. This repository provides a unified delivery pipeline for the [System76 COSMIC Desktop Environment](https://github.com/pop-os/cosmic-epoch) on **Debian Testing** and **Debian Unstable**.

> **Note:** This is an unofficial, community-maintained convenience packaging effort. It is not affiliated with, endorsed by, or an official product of the Debian Project or System76.

---

## 🏗️ Delivery Formats

We provide two primary delivery formats to cater to different user needs:

### 1. Monorepo .deb Packages
Unified Debian packages for traditional installation.
- **`cosmic-epoch-monorepo`**: The full Core DE stack (Compositor, Panel, Settings, etc.).
- **`cosmic-utils-monorepo`**: A curated set of community applet extensions (`clippy-land`, `cosmic-ext-applet-dict`, `cosmic-ext-applet-tempest`), packaged separately so they can be built and updated independently of the core DE stack.

Packages are automatically versioned (e.g., `1.0.11-1.build42`) and promoted to [GitHub Releases](https://github.com/rickysarraf/debian-cosmic/releases).

### 2. System Extensions (`sysext`)
Optimized OCI images for `systemd-sysext`, allowing you to run COSMIC without polluting your host's `/usr`.
- Delivered via the GitHub Container Registry (GHCR).
- **Disclaimer:** `systemd-sysext` delivery is intended for power-users, immutable-host setups, and rapid testing. It is not the recommended path for typical desktop installs — prefer the native `.deb` packages above unless you specifically need a non-destructive overlay.

---

## 📅 Build Schedule
Fresh builds are "baked" every **Friday at 23:59 UTC**, ensuring a crisp Saturday morning experience for our users.

### CI package/image reuse policy

Pushes to `main` may reuse **both** packages from one successful `main` run of
this same workflow and repository. The resolver checks the complete `images/`
and root `packaging/` Git trees, the full reusable build recipe
(`.github/workflows/package-build.yml`), the caller's build job and global build
settings, and the resolver itself. Documentation and reuse-orchestration changes
alone do not invalidate the build inputs. Builder runner OS/architecture and hosted
image OS/version are recorded separately and must match the resolver and release
runners conservatively for cross-run reuse. Fresh current-run packages instead
require valid Ubuntu/Linux x64 builder provenance; their matrix legs and release
runner may use different hosted image versions. Keep `BASE_VERSION` and the build
caller's `base_version` synchronized when updating versions.

Each full main build records its run/attempt, static input fingerprint, builder
runner environment, exact package version and SHA256, and preserved GHCR manifest
digest in `metadata.json` beside
each package artifact and in separate lightweight `<package>-provenance`
artifacts. Images are retained as `run-<run-id>-attempt-<attempt>` tags.
CI screens both lightweight records for source identity, build fingerprint and
package/image metadata before downloading either large `.deb` artifact. The
metadata beside each downloaded `.deb` must match its screened record exactly.
Before skipping either build, CI verifies actual Debian headers and hashes, and checks both
immutable images exist. `:latest` is promoted from those exact digests, never
used as a reuse source; release notes identify the immutable image references.
The two `:latest` tags update sequentially (GHCR has no atomic pair update);
immutable release references remain authoritative if promotion is interrupted.

Missing/expired artifacts, legacy metadata, different versions/settings,
unavailable images or API/validation errors reject reuse and rebuild **both**
packages. Acceptance/rejection reasons appear in the resolver logs. Selection
is revalidated at release; a disappeared or changed source fails the release
rather than mixing runs or falling back to current artifacts. Search is bounded
to the latest 100 successful main runs; older pairs cause a safe rebuild.
GHCR tags should be retained at least as long as their package artifacts.
Unrecognized workflow syntax disables reuse; fresh builds can still record
conservative whole-workflow provenance and release their own complete pair.

Scheduled and manually dispatched runs always build fresh. PR and `wip/*`
pushes retain per-context path gating (root packaging changes affect both).
PR-only artifacts are never reusable: they are not trusted release sources and
have no corresponding preserved OCI images. Large CI artifacts are staged under
`~/NoBackup/GEMINI_SCRATCH/`; package builds and installation tests use containers.

---

## 🛠️ Getting Started

### Prerequisites
- **Debian Testing or Sid** host.
- **systemd** >= 248 (for sysext).
- **Docker** (for `cosmic-update` and local builds).

### Building Locally
You can build the monorepo packages locally using the provided `justfile`:
```bash
# Build and extract .debs to ./dist/
just package-debs
```

### Installation

#### Option 1: Official APT Repository (Recommended)
Add our signed repository to your Debian Testing/Sid system for automatic updates:

```bash
# 1. Add the repository public key
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://rickysarraf.github.io/debian-cosmic/debian-cosmic.gpg | sudo gpg --dearmor -o /etc/apt/keyrings/debian-cosmic.gpg

# 2. Add the repository to your sources
echo "deb [signed-by=/etc/apt/keyrings/debian-cosmic.gpg] https://rickysarraf.github.io/debian-cosmic/ unstable main" | sudo tee /etc/apt/sources.list.d/debian-cosmic.list

# 3. Update and install
sudo apt update
sudo apt install cosmic-epoch-monorepo
# Optionally, install the curated applets package too:
sudo apt install cosmic-utils-monorepo
```

#### Option 2: Direct .deb Download
Download the `.deb` files directly from our [Releases](https://github.com/rickysarraf/debian-cosmic/releases) page and install them manually:
```bash
sudo apt install ./cosmic-epoch-monorepo*.deb
```

#### Option 3: System Extension (`sysext`)
Run COSMIC as a `systemd-sysext` overlay — no changes to your host `/usr`.

**Quick start:**
```bash
# 1. Pull the latest COSMIC images
sudo bin/cosmic-update

# 2. Build and install the ABI-safety canary
./bin/generate-cosmic-canary.sh
sudo apt install ./cosmic-canary_*.deb

# 3. Activate COSMIC
bin/cosmic-toggle on

# 4. Restart the display manager
sudo systemctl restart gdm
```

For the full setup guide, update workflow, ABI-safety details, and troubleshooting, see **[`bin/README.md`](bin/README.md)**.

---

## 🤝 Contributing
We use a **"Sanitized Host"** principle. All development and builds must occur in isolated environments (Docker or chroot) to prevent host contamination.

See `GEMINI.md` for core mandates and technical architecture.
