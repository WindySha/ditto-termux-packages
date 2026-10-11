#!/bin/bash
# Check out termux-packages at $TERMUX_PACKAGES_COMMIT into <dir>, with termux-packages.patch
# (Ditto's prefix and package fixes) and ci/ci.patch (download dependencies from this
# repository) applied.
#
#   ci/checkout.sh <dir>
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
git init -q "$1"
cd "$1"
git fetch -q --depth 1 https://github.com/termux/termux-packages "$TERMUX_PACKAGES_COMMIT"
git checkout -q FETCH_HEAD
git apply "$root/termux-packages.patch"
git apply "$root/ci/ci.patch"
