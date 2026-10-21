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

---

## 6. CI Package/Image Reuse Policy

Pushes to `main` may reuse **both** packages from one successful run of this
same workflow and repository: a `main` build or a same-repository PR build,
never a fork. The resolver walks successful runs newest first, so a merge whose
build inputs are unchanged (a README-only PR, say) still reaches the run that
built the pair, even when the `main` runs since then reused it and built nothing.
The resolver checks the complete `images/`
and root `packaging/` Git trees, the full reusable build recipe
(`.github/workflows/package-build.yml`), the caller's build job and global build
settings, and the resolver itself. Documentation and reuse-orchestration changes
alone do not invalidate the build inputs. Builder runner OS/architecture and hosted
image OS/version are recorded separately. For cross-run reuse the runner OS,
architecture and hosted image OS must match the resolver and release runners;
the hosted image version may differ, because rollouts are continuous and the
build itself runs in containers. Fresh current-run packages require valid
Ubuntu/Linux x64 builder provenance. Keep `BASE_VERSION` and the build
caller's `base_version` synchronized when updating versions.

Each main build and each same-repository PR build records its run/attempt,
static input fingerprint, builder
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
to the latest 100 successful runs of the workflow; older pairs cause a safe
rebuild. A reused release carries the source run's package version
(`<base>.build<source run number>`), so a merged PR ships the exact packages and
images its CI built and tested.
GHCR tags should be retained at least as long as their package artifacts.
Unrecognized workflow syntax disables reuse; fresh builds can still record
conservative whole-workflow provenance and release their own complete pair.

Scheduled and manually dispatched runs always build fresh. PR and `wip/*`
pushes retain per-context path gating (root packaging changes affect both).
A PR that builds only one leg therefore leaves no complete pair, and its merge
rebuilds both. Fork PRs and `wip/*` pushes never push images or record
provenance, so they are never release sources. Large CI artifacts are staged under
`~/NoBackup/GEMINI_SCRATCH/`; package builds and installation tests use containers.
