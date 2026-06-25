# syntax=docker/dockerfile:1
# Stage 1: Builder
FROM debian:testing AS builder

ENV DEBIAN_FRONTEND=noninteractive

# 1. Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential git just cargo rustc pkg-config \
    libpipewire-0.3-dev libspa-0.2-dev libwayland-dev libxkbcommon-dev \
    libinput-dev libseat-dev libudev-dev libgbm-dev libdrm-dev \
    libdbus-1-dev libpam0g-dev libfontconfig-dev libfreetype-dev \
    libpolkit-gobject-1-dev libgudev-1.0-dev libglib2.0-dev \
    libjson-glib-dev libpulse-dev libasound2-dev libssl-dev \
    libflatpak-dev libostree-dev libarchive-dev libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libgstreamer-plugins-bad1.0-dev libcamera-dev libv4l-dev \
    libevent-dev libyaml-dev libusb-1.0-0-dev libgnutls28-dev \
    libxcb-shape0-dev libxcb-xfixes0-dev libvulkan-dev \
    libfprint-2-dev clang llvm-dev cmake \
    libpixman-1-dev libwayland-bin libdisplay-info-dev libxcb-xinput-dev \
    wayland-protocols extra-cmake-modules scdoc sed make libclang-dev \
    gtk-update-icon-cache hicolor-icon-theme bsdextrautils patch libcairo2-dev \
    libpoppler-glib-dev \
    && rm -rf /var/lib/apt/lists/*

# Cargo caching for CI
ENV CARGO_HOME=/usr/local/cargo
ENV PATH=$CARGO_HOME/bin:$PATH
ENV CARGO_TARGET_DIR=/build/target
ENV CARGO_PROFILE_RELEASE_LTO=thin
ENV CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16
ENV LIBCLANG_PATH=/usr/lib/llvm-21/lib

WORKDIR /build
RUN mkdir -p /export/usr

COPY dbus-toggle.patch /build/
# 2. Batch clone, build, install, and clean in a single cached layer
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    --mount=type=cache,target=/build/target \
    set -eux; \
    build_release_repo() { \
        repo_dir="$1"; \
        repo_url="$2"; \
        git clone --depth 1 "$repo_url" "$repo_dir"; \
        cd "$repo_dir"; \
        just build-release; \
        just rootdir=/export prefix=/usr install; \
        cd /build; \
        rm -rf "$repo_dir"; \
    }; \
    build_repo() { \
        repo_dir="$1"; \
        repo_url="$2"; \
        git clone --depth 1 "$repo_url" "$repo_dir"; \
        cd "$repo_dir"; \
        just build; \
        just rootdir=/export prefix=/usr install; \
        cd /build; \
        rm -rf "$repo_dir"; \
    }; \
    build_release_repo cosmic-ext-tweaks https://github.com/cosmic-utils/tweaks.git; \
    build_release_repo cosmic-ext-applet-external-monitor-brightness https://github.com/cosmic-utils/cosmic-ext-applet-external-monitor-brightness.git; \
    git clone --depth 1 https://github.com/cosmic-utils/clipboard-manager.git clipboard-manager; \
    cd clipboard-manager; \
    patch -p1 < /build/dbus-toggle.patch; \
    just build-release; \
    just rootdir=/export prefix=/usr install; \
    cd /build; \
    rm -rf clipboard-manager; \
    build_release_repo cosmic-ext-applet-vigil https://github.com/cosmic-utils/cosmic-ext-applet-vigil.git; \
    build_release_repo chronos https://github.com/cosmic-utils/chronos.git; \
    build_release_repo calculator https://github.com/cosmic-utils/calculator.git; \
    build_release_repo tasks https://github.com/cosmic-utils/tasks.git; \
    build_release_repo app-hub https://github.com/cosmic-utils/app-hub.git; \
    build_release_repo stellarshot https://github.com/cosmic-utils/stellarshot.git; \
    build_release_repo forecast https://github.com/cosmic-utils/forecast.git; \
    build_release_repo examine https://github.com/cosmic-utils/examine.git; \
    build_release_repo camera https://github.com/cosmic-utils/camera.git; \
    build_release_repo cosmic-ext-applet-ollama https://github.com/cosmic-utils/cosmic-ext-applet-ollama.git; \
    build_release_repo minimon-applet https://github.com/cosmic-utils/minimon-applet.git; \
    build_repo cosmic-ext-applet-weather https://github.com/cosmic-utils/cosmic-ext-applet-weather.git; \
    build_repo cosmic-ext-applet-sysinfo https://github.com/cosmic-utils/cosmic-ext-applet-sysinfo.git; \
    build_release_repo cosmic-ext-applet-logomenu https://github.com/cosmic-utils/cosmic-ext-applet-logomenu.git; \
    build_release_repo noctua https://github.com/cosmic-utils/noctua.git

# 3. SANitization: Remove fundamental system binaries
RUN rm -f /export/usr/bin/env /export/usr/bin/bash /export/usr/bin/sh /export/usr/bin/dash

# Prepare metadata
RUN mkdir -p /export/usr/lib/extension-release.d && \
    echo 'ID=debian' > /export/usr/lib/extension-release.d/extension-release.cosmic-utils && \
    echo 'SYSEXT_LEVEL=1' >> /export/usr/lib/extension-release.d/extension-release.cosmic-utils

# Stage 2: Packaging (Sysext)
FROM busybox AS sysext
COPY --from=builder /export/usr /usr

# Stage 3: Packaging (.deb)
FROM debian:testing AS deb-packager
RUN apt-get update && apt-get install -y bsdextrautils && rm -rf /var/lib/apt/lists/*
WORKDIR /pkg
COPY --from=builder /export/usr ./usr
# Final safety check: Remove any essential system binaries that might have leaked in
RUN rm -f ./usr/bin/env ./usr/bin/bash ./usr/bin/sh ./usr/bin/dash ./usr/bin/python*
COPY packaging/debian ./DEBIAN
RUN chmod -R 755 ./DEBIAN
# Ensure version consistency
RUN dpkg-deb --build . /cosmic-utils-monorepo.deb

# Final stage: just for artifact extraction
FROM busybox
COPY --from=sysext /usr /usr
COPY --from=deb-packager /cosmic-utils-monorepo.deb /cosmic-utils-monorepo.deb

LABEL org.opencontainers.image.source="https://github.com/rickysarraf/debian-cosmic"
LABEL org.opencontainers.image.description="COSMIC Community Utilities (Sidecar Sysext and .deb Package)"
LABEL org.opencontainers.image.licenses="GPL-3.0"

CMD ["sh"]
