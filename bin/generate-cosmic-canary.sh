#!/bin/bash
set -e

# JIT Canary Generator for Debian COSMIC
# This script scans ELF binaries in a staging directory, identifies their linked
# shared library dependencies, and resolves them to host Debian packages.
# It applies a tiered zone model (Strict vs. Relaxed) to generate a dependency list,
# creating an equivs control file to build an ABI safety canary package.

show_help() {
  echo "Usage: $0 [options] <staging_directory>"
  echo ""
  echo "Options:"
  echo "  --raw       Output only the comma-separated dependencies string to stdout"
  echo "  --help, -h  Show this help message"
  echo ""
}

RAW_MODE=false
TARGET_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --raw)
      RAW_MODE=true
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      if [ -z "$TARGET_DIR" ]; then
        TARGET_DIR="$1"
        shift
      else
        echo "Error: Unknown argument $1" >&2
        show_help
        exit 1
      fi
      ;;
  esac
done

if [ -z "$TARGET_DIR" ]; then
  echo "Error: Staging directory not specified." >&2
  show_help
  exit 1
fi

if [ ! -d "$TARGET_DIR" ]; then
  echo "Error: Directory '$TARGET_DIR' does not exist." >&2
  exit 1
fi

# 1. Scan staging directory for ELF binaries and extract linked libraries
libs=$(find "$TARGET_DIR" -type f | while read -r file; do
  if file "$file" | grep -qE 'ELF (64|32)-bit'; then
    ldd "$file" 2>/dev/null | awk '/=>/ {print $3}'
  fi
done | sort -u)

if [ -z "$libs" ]; then
  echo "Error: No ELF binaries or shared libraries found in '$TARGET_DIR'." >&2
  exit 1
fi

# 2. Resolve libraries to Debian packages
packages=""
for lib in $libs; do
  if [ -f "$lib" ]; then
    pkg=$(dpkg -S "$(realpath "$lib")" 2>/dev/null | cut -d: -f1 | head -n1 | cut -d, -f1 | cut -d: -f1)
    if [ -n "$pkg" ]; then
      packages="$packages $pkg"
    fi
  fi
done

# Deduplicate packages
packages=$(echo "$packages" | tr ' ' '\n' | sort -u | xargs)

# 3. Apply Tiered Logic to classify dependencies
relaxed_deps=""
strict_deps=""

is_relaxed() {
  local p="$1"
  case "$p" in
    libc6*|libgcc-s1*|libstdc++6*|libwayland*|libdbus*|libpam*|libglib*|libasound*|libssl*|libx11*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

for pkg in $packages; do
  version=$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null || true)
  if [ -z "$version" ]; then
    continue
  fi
  
  if is_relaxed "$pkg"; then
    relaxed_deps="$relaxed_deps, $pkg (>= $version)"
  else
    strict_deps="$strict_deps, $pkg (= $version)"
  fi
done

# Combine and clean leading commas
all_deps=$(echo "$relaxed_deps $strict_deps" | sed 's/^, //; s/ , /, /g' | xargs)

if $RAW_MODE; then
  echo "$all_deps"
  exit 0
fi

# 4. Generate equivs control file
VERSION=${CANARY_VERSION:-"1.4.0-jit-$(date +%Y%m%d)"}
CONTROL_FILE="cosmic-canary.control"

cat << EOF > "$CONTROL_FILE"
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
EOF

echo "✅ Generated $CONTROL_FILE with version $VERSION"
echo "Build the package using: equivs-build $CONTROL_FILE"
