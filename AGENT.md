# AGENT.md — Agent Guidelines, Best Practices & Lessons Learned

This document serves as the operational handbook for AI agents working on the `debian-cosmic` project. It records mandatory best practices, lessons learned from past build/CI incidents, diagnostic workflows, and release conventions.

---

## 1. Build Patching & Shell Safety (CRITICAL)

### Avoid Delimiter Collisions in `sed`
* **Lesson Learned:** Using vertical bar `|` as a `sed` delimiter when modifying Rust files containing closure expressions (`|info|`, `|x|`) causes `sed` syntax errors (`sed: unknown option to 's'`), leading to catastrophic Docker build failures in long CI pipelines.
* **Mandate:**
  1. Never use `|` as a `sed` delimiter for Rust or shell string replacements. Use `#` or `@` instead.
  2. For complex multi-line patches, prefer creating dedicated `.patch` files and applying them via `git apply` or `patch -p1`, or use python string replacements.
  3. **Empirical Local Testing:** ALWAYS test inline `sed` or patch commands directly against a target source file in local scratch space (`/tmp` or `~/NoBackup/AGENT_SCRATCH`) before committing changes to `Dockerfile` or build scripts.

---

## 2. Git Branch Hygiene & Upstream Synchronization

### Preventing Split-Brain & Duplicate Commits
* **Lesson Learned:** Creating feature branches before merging upstream fast-forwards/syncs causes duplicate commits and merge conflicts (`2 commits ahead, 1 commit behind`).
* **Mandate:**
  1. Always branch off the latest `main` commit (`git checkout -B <branch> origin/main`).
  2. When an upstream sync PR (e.g. `1.5.0-1`) is merged, immediately rebase open feature branches (`git rebase main`) to ensure clean history.
  3. Ensure feature PRs contain strictly 1 clean, atomic commit for the target feature/fix.

### Updating Checked-Out Local Branches
* **Lesson Learned:** Git refuses to overwrite the currently checked-out branch during a direct refspec fetch (`git fetch <url> branch:branch`).
* **Mandate:**
  To safely update a local checked-out branch from Gitea or upstream, use:
  ```bash
  git fetch <url> <branch>
  git reset --hard FETCH_HEAD
  ```

---

## 3. COSMIC DE Diagnostics & Crash Traceability

### Diagnostic Protocol via `camp-dbus`
* Access systemd and journald user logs using `camp-dbus journalctl --user`.
* **Failure Chain Analysis:**
  1. **Wayland Layer:** Watch for `xdg_positioner: error 0: Invalid size for positioner's anchor rectangle.`
  2. **Socket Layer:** Compositor severs Wayland display (`Connection reset by peer (os error 104)`).
  3. **Daemon Logging Layer:** Standard Rust `println!` / `eprintln!` panics on `Broken pipe (os error 32)` when stdio is severed.
  4. **IPC / D-Bus Layer:** `cosmic-notifications` panic tears down the panel D-Bus server, causing cascading `SIGABRT` across `cosmic-panel` and all applets.
* **Daemon Robustness:** Core background services (`cosmic-notifications`) MUST ignore `SIGPIPE` and handle stdio disconnections gracefully to prevent tearing down desktop session infrastructure.

---

## 4. Release Engineering & Versioning

* **Version Synchronization:** Ensure package versions are updated atomically across all manifest locations:
  - `.github/workflows/build-packages.yml` (`BASE_VERSION: "X.Y.Z-N"`)
  - `justfile` (`VERSION := "X.Y.Z-N~local1"`)
  - `packaging/cosmic-epoch/debian/changelog`
  - `images/cosmic-epoch/packaging/debian/changelog`
  - `packaging/cosmic-utils/debian/changelog`
  - `images/cosmic-utils/packaging/debian/changelog`
* **Debian Changelog Formatting:** Follow standard Debian changelog syntax with proper urgency levels (`low`, `medium`, `high`) and ISO/RFC 2822 timestamps.

---

## 5. CI Decoupling: `cosmic-epoch` vs `cosmic-utils`

* **Lesson Learned:** `cosmic-epoch` is a ~5 hour build (full DE compositor/panel/settings stack). `cosmic-utils` (a handful of community applets) builds in minutes. Coupling them in a single unconditional matrix job means every `cosmic-utils`-only change pays the full `cosmic-epoch` build cost.
* **Mandate:**
  1. Use a `dorny/paths-filter` `changes` job to detect which image context(s) actually changed (`images/cosmic-epoch/**` vs `images/cosmic-utils/**`).
  2. Gate each `build-and-push` matrix leg on its own path-filter output, so `push`/`pull_request` events only rebuild the leg(s) that changed.
  3. Always build **both** legs unconditionally on `schedule`/`workflow_dispatch` (the weekly rolling-release build), regardless of path filters.
  4. **Never** include the workflow file itself (`.github/workflows/build-packages.yml`) in either leg's path filter — doing so re-triggers a full rebuild of both legs on any CI-only change, defeating the decoupling.
  5. Downstream jobs (`release`, `deploy-pages`) that `needs:` the matrix job must tolerate a partially-skipped matrix (`result != 'failure' && result != 'cancelled'`, not merely `== 'success'`), since path-filtered runs can legitimately skip one leg.
