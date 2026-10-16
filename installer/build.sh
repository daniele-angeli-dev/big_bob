#!/bin/sh
# Compila BIG-BOB-Setup.exe dal commit corrente (serve NSIS: apt install nsis / choco install nsis).
set -e
cd "$(dirname "$0")/.."
SHA=$(git rev-parse HEAD)
VER=$(git log -1 --format=%cd --date=format:%Y.%m.%d)-$(git rev-parse --short HEAD)
rm -rf installer/build
mkdir -p installer/build/app
git archive HEAD | tar -x -C installer/build/app
rm -rf installer/build/app/installer
echo "$SHA" > installer/build/app/VERSION
makensis -V2 -DVERSION="$VER" -DSRC="build/app" -DOUT="build/BIG-BOB-Setup.exe" installer/bigbob.nsi
echo "Creato installer/build/BIG-BOB-Setup.exe ($VER)"
