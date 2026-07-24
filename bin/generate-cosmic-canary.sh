#!/bin/bash
set -euo pipefail

# JIT Canary Generator for Debian COSMIC
# This script scans ELF binaries in a staging directory, identifies their linked
# shared library dependencies, and resolves them to host Debian packages.
# It applies a tiered zone model (Strict vs. Relaxed) to generate a dependency list,
# creating an equivs control file and, by default, building the ABI safety canary package.

DEFAULT_TARGET_DIR="/var/lib/extensions/cosmic/usr"
CONTROL_FILE="cosmic-canary.control"
RAW_MODE=false
CONTROL_ONLY=false
TARGET_DIR="$DEFAULT_TARGET_DIR"
TARGET_DIR_SET=false

show_help() {
  echo "Usage: $0 [options] [staging_directory]"
  echo ""
  echo "Options:"
  echo "  --control-only  Generate only ${CONTROL_FILE} without building the .deb"
  echo "  --raw           Output only the comma-separated dependencies string to stdout"
  echo "  --help, -h      Show this help message"
  echo ""
  echo "If no staging directory is provided, the script defaults to: ${DEFAULT_TARGET_DIR}"
}

fail() {
  echo "Error: $*" >&2
  exit 1
}

check_required_commands() {
  local cmd
  local missing=()

  for cmd in awk date dpkg dpkg-query equivs-build file find grep ldd realpath sort; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      missing+=("$cmd")
    fi
  done

  if ((${#missing[@]} > 0)); then
    fail "Missing required command(s): ${missing[*]}. Please install them and retry."
  fi
}

is_relaxed() {
  local pkg="$1"
  case "$pkg" in
    libc6*|libgcc-s1*|libstdc++6*|libwayland*|libdbus*|libpam*|libglib*|libasound*|libssl*|libx11*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --control-only)
      CONTROL_ONLY=true
      shift
      ;;
    --raw)
      RAW_MODE=true
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      if ! $TARGET_DIR_SET; then
        TARGET_DIR="$1"
        TARGET_DIR_SET=true
        shift
      else
        fail "Unknown argument: $1"
      fi
      ;;
  esac
done

if $RAW_MODE && $CONTROL_ONLY; then
  fail "--raw and --control-only cannot be used together."
fi

check_required_commands

if [[ ! -d "$TARGET_DIR" ]]; then
  fail "Directory '$TARGET_DIR' does not exist."
fi

TARGET_DIR=$(realpath "$TARGET_DIR")

declare -a libs
mapfile -t libs < <(
  find "$TARGET_DIR" -type f | while IFS= read -r staged_file; do
    if file "$staged_file" | grep -qE 'ELF (64|32)-bit'; then
      (ldd "$staged_file" 2>/dev/null || true) | awk '/=>/ {print $3}'
    fi
  done | sort -u
)

if ((${#libs[@]} == 0)); then
  fail "No ELF binaries or shared libraries found in '$TARGET_DIR'."
fi

declare -A package_map=()
for lib in "${libs[@]}"; do
  [[ -f "$lib" ]] || continue

  pkg=$(dpkg -S "$(realpath "$lib")" 2>/dev/null | awk -F'[:,]' 'NR == 1 {print $1; exit}')
  if [[ -n "$pkg" ]]; then
    package_map["$pkg"]=1
  fi
done

if ((${#package_map[@]} == 0)); then
  fail "Unable to resolve staged ELF dependencies to Debian packages."
fi

declare -a packages
mapfile -t packages < <(printf '%s\n' "${!package_map[@]}" | sort)

declare -a dependency_entries=()
for pkg in "${packages[@]}"; do
  version=$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null || true)
  [[ -n "$version" ]] || continue

  if is_relaxed "$pkg"; then
    dependency_entries+=("$pkg (>= $version)")
  else
    dependency_entries+=("$pkg (= $version)")
  fi
done

if ((${#dependency_entries[@]} == 0)); then
  fail "Unable to determine package versions for the detected dependencies."
fi

all_deps=""
for dependency in "${dependency_entries[@]}"; do
  if [[ -n "$all_deps" ]]; then
    all_deps+=", "
  fi
  all_deps+="$dependency"
done

if $RAW_MODE; then
  echo "$all_deps"
  exit 0
fi

VERSION=${CANARY_VERSION:-"1.4.0-jit-$(date +%Y%m%d)"}

cat <<EOF_CONTROL > "$CONTROL_FILE"
Section: misc
Priority: optional
Standards-Version: 3.9.2
Package: cosmic-canary
Version: $VERSION
Architecture: all
Maintainer: Ritesh Raj Sarraf <rrs@debian.org>
Depends: $all_deps
Description: ABI-safety JIT canary for Debian COSMIC System Extension
 This package pins critical library versions to ensure the host system's
 libraries remain ABI-compatible with the active COSMIC system extension.
EOF_CONTROL

control_path=$(realpath "$CONTROL_FILE")
echo "✅ Generated ${control_path} with version ${VERSION}"

if $CONTROL_ONLY; then
  echo "ℹ️  Control-only mode enabled; skipping package build."
  exit 0
fi

equivs-build "$CONTROL_FILE"

package_file="cosmic-canary_${VERSION}_all.deb"
if [[ -f "$package_file" ]]; then
  echo "✅ Built Debian package: $(realpath "$package_file")"
else
  echo "✅ Built Debian package artifacts in $(pwd)"
fi
