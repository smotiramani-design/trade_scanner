#!/usr/bin/env bash
#
# build_lambda_zip.sh — produce a Lambda-ready zip with Linux-built dependencies.
#
# Why this exists: pandas/numpy/yfinance/psycopg contain compiled binaries. The
# copies installed on your Mac are macOS binaries and will crash on Lambda
# (Amazon Linux). This script downloads the *Linux* wheels for the chosen Lambda
# architecture and bundles them with the project source.
#
# Usage:
#   ./build_lambda_zip.sh                 # x86_64 (default), Python 3.11
#   LAMBDA_ARCH=arm64 ./build_lambda_zip.sh
#
# Output: dist/trade_scanner_lambda.zip
#   - Likely >50 MB, so upload it to Lambda via S3 (not console drag-and-drop):
#       aws s3 cp dist/trade_scanner_lambda.zip s3://YOUR_BUCKET/
#       aws lambda update-function-code --function-name trade-scanner \
#           --s3-bucket YOUR_BUCKET --s3-key trade_scanner_lambda.zip
#
set -euo pipefail
cd "$(dirname "$0")"

PYVER="${LAMBDA_PYTHON_VERSION:-3.11}"
ARCH="${LAMBDA_ARCH:-x86_64}"
case "$ARCH" in
  x86_64) PLATFORM="manylinux2014_x86_64" ;;
  arm64)  PLATFORM="manylinux2014_aarch64" ;;
  *) echo "Unknown LAMBDA_ARCH='$ARCH' (use x86_64 or arm64)"; exit 1 ;;
esac

BUILD_DIR="build/lambda"
PKG="$BUILD_DIR/package"
OUT_DIR="dist"
ZIP="$OUT_DIR/trade_scanner_lambda.zip"

echo "▶ Building Lambda zip  (python=$PYVER  arch=$ARCH  platform=$PLATFORM)"
rm -rf "$BUILD_DIR" "$ZIP"
mkdir -p "$PKG" "$OUT_DIR"

# ── 1. Dependencies, built for the Lambda runtime ─────────────────────────────
echo "▶ Installing dependencies for $PLATFORM ..."
python3 -m pip install \
  --platform "$PLATFORM" \
  --target "$PKG" \
  --implementation cp \
  --python-version "$PYVER" \
  --abi "cp${PYVER//./}" \
  --only-binary=:all: \
  --upgrade \
  -r requirements-lambda.txt

# ── 2. Project source code ────────────────────────────────────────────────────
echo "▶ Copying project source ..."
SRC_FILES=(lambda_function.py config.py scanner.py universes.py)
SRC_DIRS=(signals data trading utils db)
for f in "${SRC_FILES[@]}"; do cp "$f" "$PKG/"; done
for d in "${SRC_DIRS[@]}"; do
  rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='*copy.py' "$d" "$PKG/"
done

# ── 3. Trim weight (tests, caches, metadata we don't need at runtime) ─────────
echo "▶ Pruning build to reduce size ..."
find "$PKG" -type d -name '__pycache__' -prune -exec rm -rf {} \;
find "$PKG" -type d -name 'tests' -prune -exec rm -rf {} \;
find "$PKG" -type f -name '*.pyc' -delete

# ── 4. Zip (contents at the root, as Lambda requires) ─────────────────────────
echo "▶ Zipping ..."
( cd "$PKG" && zip -qr9 "$OLDPWD/$ZIP" . )

SIZE=$(du -h "$ZIP" | cut -f1)
echo "✔ Built $ZIP  ($SIZE)"
echo "  Handler:  lambda_function.lambda_handler"
echo "  If >50MB, upload via S3 (see header of this script)."
