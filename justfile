VERSION := "1.3.0-1~local1"

# Build all COSMIC monorepo .deb packages
package-debs:
    @echo "🏗️ Injecting version {{VERSION}}..."
    sed -i "s/@VERSION@/{{VERSION}}/g" images/cosmic-epoch/packaging/debian/control
    @echo "🏗️ Building Cosmic Epoch monodeb..."
    docker buildx build --load -t cosmic-epoch-deb images/cosmic-epoch
    @echo "⏪ Restoring control files..."
    git checkout images/cosmic-epoch/packaging/debian/control
    mkdir -p dist
    @echo "📦 Extracting packages to ./dist/..."
    docker run --rm -v $(pwd)/dist:/dist cosmic-epoch-deb cp /cosmic-epoch-monorepo.deb /dist/
    @echo "✅ Build complete. Packages located in ./dist/"

# Clean build artifacts
clean:
    rm -rf dist
