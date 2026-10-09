#!/bin/sh
# Points README.md at the picture as it is in the current commit.
#
# raw.githubusercontent.com resolves a branch lazily: right after a push, a URL with `main` in it
# can still serve the previous picture, and the CDN then keeps that for five minutes. A URL with a
# commit in it always means one and the same file, so the README shows exactly what was committed.
# Run it after committing assets/terminal.svg, then commit README.md.
set -e
sha=$(git rev-parse HEAD)
url="https://raw.githubusercontent.com/antondanv/antondanv/$sha/assets/terminal.svg"
sed -E "s#src=\"[^\"]*terminal\.svg[^\"]*\"#src=\"$url\"#" README.md > README.md.tmp
mv README.md.tmp README.md
