VERSION := "1.5.0-2~local1"
DEB_PACKAGE := "cosmic-epoch-monorepo.deb"
UTILS_DEB_PACKAGE := "cosmic-utils-monorepo.deb"

# Default target: show help
default:
    @just --list

# Build cosmic-epoch container image and export sidecar sysext + deb package
build-epoch:
    docker buildx build --output type=local,dest=./build-output-epoch ./images/cosmic-epoch

# Build cosmic-utils container image and export sidecar sysext + deb package
build-utils:
    docker buildx build --output type=local,dest=./build-output-utils ./images/cosmic-utils

# Build all container images (epoch + utils)
build-all: build-epoch build-utils

# Extract built sysext images from output directories
extract-sysext:
    @mkdir -p ./dist
    @if [ -f ./build-output-epoch/cosmic-epoch.raw ]; then \
        cp ./build-output-epoch/cosmic-epoch.raw ./dist/cosmic-epoch-$(VERSION).raw; \
        echo "Extracted ./dist/cosmic-epoch-$(VERSION).raw"; \
    fi
    @if [ -f ./build-output-utils/cosmic-utils.raw ]; then \
        cp ./build-output-utils/cosmic-utils.raw ./dist/cosmic-utils-$(VERSION).raw; \
        echo "Extracted ./dist/cosmic-utils-$(VERSION).raw"; \
    fi

# Extract built deb packages from output directories
extract-deb:
    @mkdir -p ./dist
    @if [ -f ./build-output-epoch/$(DEB_PACKAGE) ]; then \
        cp ./build-output-epoch/$(DEB_PACKAGE) ./dist/cosmic-epoch-monorepo_$(VERSION)_amd64.deb; \
        echo "Extracted ./dist/cosmic-epoch-monorepo_$(VERSION)_amd64.deb"; \
    fi
    @if [ -f ./build-output-utils/$(UTILS_DEB_PACKAGE) ]; then \
        cp ./build-output-utils/$(UTILS_DEB_PACKAGE) ./dist/cosmic-utils-monorepo_$(VERSION)_amd64.deb; \
        echo "Extracted ./dist/cosmic-utils-monorepo_$(VERSION)_amd64.deb"; \
    fi

# Build all COSMIC monorepo .deb packages (epoch + utils)
package-debs: build-all extract-deb
    @echo "✅ Build complete. Packages located in ./dist/"

# Clean build artifacts
clean:
    rm -rf ./build-output-epoch ./build-output-utils ./dist
