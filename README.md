# <img src="https://www.debian.org/logos/openlogo-nd-100.png" height="36"> 🌌 Debian COSMIC

[![Debian COSMIC - Build Packages](https://github.com/rickysarraf/debian-cosmic/actions/workflows/build-packages.yml/badge.svg)](https://github.com/rickysarraf/debian-cosmic/actions/workflows/build-packages.yml)

Welcome to the standalone **Debian COSMIC** project. This repository provides a unified delivery pipeline for the [System76 COSMIC Desktop Environment](https://github.com/pop-os/cosmic) on **Debian Testing** and **Debian Unstable**.

By carving this out of the Desktop Brewery, we ensure dedicated attention to the unique packaging and delivery needs of COSMIC on Debian.

---

## 🏗️ Delivery Formats

We provide two primary delivery formats to cater to different user needs:

### 1. Monorepo .deb Packages
Unified Debian packages for traditional installation.
- **`cosmic-epoch-monorepo`**: The full Core DE stack (Compositor, Panel, Settings, etc.).

Packages are automatically versioned (e.g., `1.0.11-1.build42`) and promoted to [GitHub Releases](https://github.com/rickysarraf/debian-cosmic/releases).

### 2. System Extensions (`sysext`)
Optimized OCI images for `systemd-sysext`, allowing you to run COSMIC without polluting your host's `/usr`.
- Delivered via the GitHub Container Registry (GHCR).

---

## 📅 Build Schedule
Fresh builds are "baked" every **Friday at 23:59 UTC**, ensuring a crisp Saturday morning experience for our users.

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
```

#### Option 2: Direct .deb Download
Download the `.deb` files directly from our [Releases](https://github.com/rickysarraf/debian-cosmic/releases) page and install them manually:
```bash
sudo apt install ./cosmic-epoch-monorepo*.deb
```

#### Option 3: System Extension (`sysext`)
For detailed instructions on using the `sysext` approach with `cosmic-toggle` and `cosmic-update`, see the `bin/` directory documentation.

---

## 🛡️ ABI Safety: JIT Canary Package

When using the `systemd-sysext` delivery format (Modular Sidecar overlays), updates to volatile host system libraries (such as the Mesa graphics drivers, Vulkan, DRM, etc.) can cause dynamic linker mismatch errors (such as black screens or segfaults).

To prevent this, we use the **JIT Canary** package (`cosmic-canary`). The canary is a custom Debian package built dynamically to match the exact ABI dependencies of the compiled COSMIC stack.

### Tiered Dependency Model
The Canary uses a conservative dependency model that defaults to strict version pinning and only relaxes a small allowlist of stable host libraries:
- **Strict Zone (`=` dependency):** Applied to every detected dependency unless it is explicitly classified as relaxed.
- **Relaxed Zone (`>=` dependency):** Limited to the allowlist of stable system layers and protocol libraries (`libc6`, `libgcc-s1`, `libstdc++6`, `libwayland*`, `libdbus*`, `libpam*`, `libglib*`, `libasound*`, `libssl*`, `libx11*`).

### Generating the Canary Package
The script expects a staged COSMIC `/usr` tree that already contains the built ELF binaries and shared libraries you want to scan. In the normal sysext workflow, that is the staged tree at `/var/lib/extensions/cosmic/usr`.

1. **Generate the control file and build the `.deb` package in one step:**
   ```bash
   ./bin/generate-cosmic-canary.sh /var/lib/extensions/cosmic/usr
   ```
   By default, this writes `cosmic-canary.control`, runs `equivs-build`, and leaves the resulting `cosmic-canary_*.deb` artifact in the current working directory. If you omit the path, the script defaults to `/var/lib/extensions/cosmic/usr`.

2. **Install on the host system:**
   ```bash
   sudo apt install ./cosmic-canary_*.deb
   ```

3. **Advanced/manual workflow:** If you only want the generated control file and plan to run `equivs-build` yourself later, use:
   ```bash
   ./bin/generate-cosmic-canary.sh --control-only /var/lib/extensions/cosmic/usr
   ```

Once installed, standard `apt upgrade` updates that violate strict graphics stack versions will be blocked, alerting you that the COSMIC system extension needs to be rebuilt.

---

## 🤝 Contributing
We use a **"Sanitized Host"** principle. All development and builds must occur in isolated environments (Docker or chroot) to prevent host contamination.

See `GEMINI.md` for core mandates and technical architecture.
