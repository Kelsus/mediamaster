#!/usr/bin/env bash
# Build the Lambda deployment directory without Docker: install manylinux/aarch64
# wheels for Python 3.12 into backend/lambda_build, then copy the app source in.
set -euo pipefail
cd "$(dirname "$0")/../backend"

BUILD_DIR=lambda_build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

uv pip install \
  --python-platform aarch64-manylinux2014 \
  --python-version 3.12 \
  --only-binary :all: \
  --target "$BUILD_DIR" \
  anthropic fastapi mangum "pyjwt[crypto]" python-ulid

cp -R src/mediamaster_api "$BUILD_DIR/mediamaster_api"
find "$BUILD_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
echo "Lambda bundle ready at backend/$BUILD_DIR"
