#!/bin/sh
# Assemble the Hugging Face Space from COMMITTED files only.
#
#   deploy/huggingface/build_space.sh <out-dir>
#
# git archive reads the commit, not the working tree, so an .env, a local
# key or anything else untracked can never reach the Space.
set -eu

OUT="${1:?usage: build_space.sh <out-dir>}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

rm -rf "$OUT"
mkdir -p "$OUT"
git -C "$REPO" archive HEAD backend frontend config LICENSE | tar -x -C "$OUT"
cp "$REPO/deploy/huggingface/Dockerfile" "$REPO/deploy/huggingface/entrypoint.sh" "$OUT/"
cp "$REPO/deploy/huggingface/README.md" "$OUT/README.md"

if grep -rIl "AIza[0-9A-Za-z_-]\{30,\}" "$OUT" >/dev/null 2>&1; then
    echo "refusing: something in $OUT looks like a Google API key" >&2
    exit 1
fi
echo "space assembled in $OUT"
