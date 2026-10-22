# Downstream Notes

This repository is a convenience packaging effort for COSMIC on Debian. It
carries a number of downstream patches and packaging decisions over upstream
(pop-os/cosmic-epoch and friends). This file collects them in one place so the
README stays lean; the README points here.

## COSMIC Store — PackageKit (apt) + Flatpak backends

The COSMIC Store lists Debian packages (via AppStream) alongside Flatpak apps,
like GNOME Software, instead of sitting on a flatpak-only build with no data
source.

- `cosmic-epoch-monorepo` Recommends `flatpak`, `packagekit`, `appstream` and
  `apt-config-icons`, so all four arrive with a standard `apt install`.
  - `flatpak` → the flatpak backend (Flathub remote is added manually, by design).
  - `packagekit` → packagekitd (D-Bus activated; no unit to enable).
  - `appstream` → the Debian apt hook fills `/var/cache/swcatalog` the store reads.
  - `apt-config-icons` → without it `apt update` skips the DEP-11 icon tarballs
    and icons stay generic (it is only Suggested by appstream, so it must be
    listed).
- Run `sudo apt update` once after installing so the Debian AppStream catalog
  and its icons are generated.
- Add Flathub for Flatpak apps:
  `flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo`
- Expect a one-time polkit prompt on the first install/removal. `packagekit`
  hard-Depends on `polkitd`, so the policy/authorization stack is pulled in
  automatically — do not list `policykit-1`/`polkitd` in Recommends.
- On the `sysext` path, install those four packages on the host yourself.

Build side: cosmic-store is built with the packagekit feature by a dedicated
patch, `images/cosmic-epoch/patches/0001-cosmic-store-packagekit-feature.patch`,
applied by the Dockerfile clone step (`patch -p1`, before the notifications
patch). It edits the epoch-root justfile's `build:` recipe,
`{{ just }} cosmic-store/build-release` →
`{{ just }} cosmic-store/build-release --features packagekit`.
`packagekit-zbus` is pure zbus, so no new `-dev` libraries are needed.

## Downstream patches — images/cosmic-epoch/patches/

- `0001-cosmic-store-packagekit-feature.patch` — build cosmic-store with the
  `packagekit` feature so the store lists Debian packages (via AppStream)
  alongside Flatpak apps, like GNOME Software. (Epoch 1.10.0 carried this same
  change inside the `0001-justfile-*` patch; that file is gone upstream on
  1.11.0, where the root justfile already uses `just` in-tree for the migrated
  components, so the feature now has its own patch.)
- `0002-cosmic-notifications-sigpipe-guard-and-libc-dep.patch` —
  `cosmic-notifications` can hit SIGPIPE on stdio when Wayland/D-Bus
  disconnects, panicking with an alarming backtrace. Ignore SIGPIPE at startup
  (and quiet the "Broken pipe" panic hook), and add `libc = "0.2"` for the
  `signal()` call.

## cosmic-utils-monorepo — curated community applets

The `cosmic-utils-monorepo` package bundles a curated set of community applets
separately from the core DE stack: **clippy-land** (clipboard manager),
**cosmic-ext-applet-dict** (dictionary), and **cosmic-ext-applet-tempest**
(weather). It is built against and strictly tied to `cosmic-epoch-monorepo`.

Downstream integration carried in the packaging:

- **clippy-land (clipboard)** — PATH-based `.desktop` `Exec` (no staging
  `/export` prefix, so it launches under a `sysext` overlay), and clipboard
  history persists across restarts (load/save `max_history`; a missing pinned
  entry deserializes as `true`).
- **cosmic-ext-applet-dict (dictionary)** — upstream embedded SQLite by
  default, with an optional local DICT-protocol backend (`dict_server`) on
  localhost dictd, plus an IPC-based `--toggle` shortcut. Both landed as
  upstream patches applied in the Debian packaging (1.5.0-2 / 1.5.0-3).
