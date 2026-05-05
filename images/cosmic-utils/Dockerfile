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
    libgstreamer-plugins-base1.0-dev clang llvm-dev cmake \
    libpixman-1-dev libwayland-bin libdisplay-info-dev libxcb-xinput-dev \
    wayland-protocols extra-cmake-modules scdoc sed make libclang-dev \
    gtk-update-icon-cache hicolor-icon-theme bsdextrautils patch \
    && rm -rf /var/lib/apt/lists/*

# Memory Safety for CI
ENV CARGO_PROFILE_RELEASE_LTO=thin
ENV CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16
ENV LIBCLANG_PATH=/usr/lib/llvm-21/lib

WORKDIR /build
RUN mkdir -p /export/usr

# 2. Batch Clone and Build
# cosmic-ext-tweaks
RUN git clone --depth 1 https://github.com/cosmic-utils/tweaks.git cosmic-ext-tweaks && \
    cd cosmic-ext-tweaks && just build-release && just rootdir=/export prefix=/usr install

# cosmic-ext-applet-external-monitor-brightness
RUN git clone --depth 1 https://github.com/cosmic-utils/cosmic-ext-applet-external-monitor-brightness.git && \
    cd cosmic-ext-applet-external-monitor-brightness && just build-release && just rootdir=/export prefix=/usr install

# clipboard-manager (Corrected repo name)
COPY dbus-toggle.patch /build/
RUN git clone --depth 1 https://github.com/cosmic-utils/clipboard-manager.git && \
    cd clipboard-manager && \
    patch -p1 < ../dbus-toggle.patch && \
    just build-release && just rootdir=/export prefix=/usr install

# cosmic-ext-applet-vigil (Keep-awake tool)
RUN git clone --depth 1 https://github.com/cosmic-utils/cosmic-ext-applet-vigil.git && \
    cd cosmic-ext-applet-vigil && just build-release && just rootdir=/export prefix=/usr install

# chronos (Pomodoro timer)
RUN git clone --depth 1 https://github.com/cosmic-utils/chronos.git && \
    cd chronos && just build-release && just rootdir=/export prefix=/usr install

# calculator (Simple calculator)
RUN git clone --depth 1 https://github.com/cosmic-utils/calculator.git && \
    cd calculator && just build-release && just rootdir=/export prefix=/usr install

# tasks (Task management application)
RUN git clone --depth 1 https://github.com/cosmic-utils/tasks.git && \
    cd tasks && just build-release && just rootdir=/export prefix=/usr install

# app-hub (AppImage Manager)
RUN git clone --depth 1 https://github.com/cosmic-utils/app-hub.git && \
    cd app-hub && just build-release && just rootdir=/export prefix=/usr install

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

LABEL org.opencontainers.image.source="https://github.com/rickysarraf/desktop-brewery"
LABEL org.opencontainers.image.description="COSMIC Community Utilities (Sidecar Sysext and .deb Package)"
LABEL org.opencontainers.image.licenses="GPL-3.0"

CMD ["sh"]
