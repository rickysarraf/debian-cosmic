# syntax=docker/dockerfile:1
# Stage 1: Builder
FROM debian:testing AS builder

ENV DEBIAN_FRONTEND=noninteractive

# 1. Add stable build dependencies
RUN apt-get update && apt-get install -y \
    build-essential git just cargo rustc pkg-config \
    libpipewire-0.3-dev libspa-0.2-dev libwayland-dev libxkbcommon-dev \
    libinput-dev libseat-dev libudev-dev libgbm-dev libdrm-dev \
    libdbus-1-dev libpam0g-dev libfontconfig-dev libfreetype-dev \
    libpolkit-gobject-1-dev libgudev-1.0-dev libglib2.0-dev \
    libjson-glib-dev libpulse-dev libasound2-dev libssl-dev \
    libflatpak-dev libarchive-dev libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev clang llvm-dev cmake \
    libpixman-1-dev libwayland-bin libdisplay-info-dev libxcb-xinput-dev libdav1d-dev \
    wayland-protocols extra-cmake-modules scdoc sed make libclang-dev \
    gtk-update-icon-cache hicolor-icon-theme bsdextrautils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 2. Rust/Cargo build configuration
ENV CARGO_HOME=/usr/local/cargo
ENV PATH=$CARGO_HOME/bin:$PATH
ENV CARGO_PROFILE_RELEASE_LTO=thin
ENV CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16
ENV CARGO_PROFILE_RELEASE_PANIC=abort
ENV LIBCLANG_PATH=/usr/lib/llvm-21/lib

COPY patches/ /patches/

# Mark the directory as safe for git
RUN git config --global --add safe.directory /build && \
    git clone --recursive --branch epoch-1.6.0 https://github.com/pop-os/cosmic-epoch.git . && \
    patch -p1 < /patches/0001-justfile-use-just-for-xdg-desktop-portal-cosmic.patch && \
    patch -p1 < /patches/0002-cosmic-notifications-sigpipe-guard-and-libc-dep.patch

# 3. Build and install FULL stack
RUN mkdir -p /export/usr && \
    just install /export /usr

# 4. SANitization: Remove fundamental system binaries to protect host integrity
RUN rm -f /export/usr/bin/env /export/usr/bin/bash /export/usr/bin/sh /export/usr/bin/dash

# Prepare metadata
RUN echo 'ID=debian' > /export/extension-release.cosmic && \
    echo 'SYSEXT_LEVEL=1' >> /export/extension-release.cosmic

# Stage 2: Packaging (Sysext)
FROM busybox AS sysext
COPY --from=builder /export/extension-release.cosmic /usr/lib/extension-release.d/extension-release.cosmic
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
# Install changelog and copyright into usr/share/doc as required by Debian policy
RUN mkdir -p ./usr/share/doc/cosmic-epoch-monorepo && \
    gzip -9 -c ./DEBIAN/changelog > ./usr/share/doc/cosmic-epoch-monorepo/changelog.Debian.gz && \
    cp ./DEBIAN/copyright ./usr/share/doc/cosmic-epoch-monorepo/copyright && \
    chmod 644 ./usr/share/doc/cosmic-epoch-monorepo/changelog.Debian.gz \
               ./usr/share/doc/cosmic-epoch-monorepo/copyright
# Ensure version consistency
RUN dpkg-deb --build . /cosmic-epoch-monorepo.deb

# Final stage: just for artifact extraction
FROM busybox
COPY --from=sysext /usr /usr
COPY --from=deb-packager /cosmic-epoch-monorepo.deb /cosmic-epoch-monorepo.deb

LABEL org.opencontainers.image.source="https://github.com/rickysarraf/desktop-brewery"
LABEL org.opencontainers.image.description="Debian COSMIC System Extension and .deb Package"
LABEL org.opencontainers.image.licenses="GPL-3.0"

CMD ["sh"]
