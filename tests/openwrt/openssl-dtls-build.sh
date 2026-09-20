#!/bin/sh
# openssl-dtls-build.sh -- build libopenssl3 WITH DTLS for OpenWrt 24.10.8.
#
# Why: the stock OpenWrt libopenssl is built with `no-dtls`
# (CONFIG_OPENSSL_WITH_DTLS off), so Asterisk's WebRTC media (DTLS-SRTP)
# fails with "no protocols available". This recipe rebuilds the same
# libopenssl3 (3.0.21-r1) with DTLS enabled. The built .so files are used
# ONLY by Asterisk via LD_PRELOAD (see tests/apu2/apu2-asterisk-dtls-preload.sh);
# the system OpenSSL is never replaced.
#
# Prereqs: the pinned SDK (24.10.8 x86_64) on a CASE-SENSITIVE volume (the
# OpenWrt preflight rejects case-insensitive filesystems), the OpenWrt v24.10.8
# package/libs/openssl tree fetched into the SDK, and .config carrying:
#   CONFIG_PACKAGE_libopenssl=y
#   CONFIG_OPENSSL_WITH_DTLS=y
# with CONFIG_ALL / CONFIG_ALL_KMODS / CONFIG_ALL_NONSHARED disabled.
# Run inside an amd64 Debian container with the SDK at /sdk; artifacts land in
# bin/packages/x86_64/base/libopenssl3_*.ipk and, more usefully, the compiled
# libs in build_dir/.../openssl-3.0.21/.pkgdir/libopenssl/usr/lib/.
#
# Verified 2026-09-20: libssl 785,712 B / libcrypto 5,044,952 B (vs stock
# 677,756 / 4,420,677); Asterisk DTLS-SRTP echo test passes.

set +x
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq build-essential bison flex \
    bc rsync git unzip wget xz-utils zlib1g-dev libssl-dev libncurses5-dev \
    file python3 python3-dev patch gawk diffutils cpio perl tar gzip \
    ca-certificates gcc g++ make libtool autoconf automake gettext >/dev/null
cd /sdk
SDK_DIR_NAME="openwrt-sdk-24.10.8-x86-64_gcc-13.3.0_musl.Linux-x86_64"
[ -d "$SDK_DIR_NAME" ] || tar xf "/sdk/${SDK_DIR_NAME}.tar.zst"
cd "$SDK_DIR_NAME"
ln -sf /sdk/dl dl
stage() { printf '%sZ %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%S')" "$*" >> /sdk/build/openssl-stage.txt; }
grep -vE "^(# )?CONFIG_PACKAGE_" .config > .config.min 2>/dev/null || cp .config .config.min
mv .config.min .config
sed -i -e "/^CONFIG_ALL=/d" -e "/^CONFIG_ALL_KMODS=/d" -e "/^CONFIG_ALL_NONSHARED=/d" -e "/^CONFIG_TARGET_ALL_PROFILES=/d" .config
printf "# CONFIG_ALL is not set\n# CONFIG_ALL_KMODS is not set\n# CONFIG_ALL_NONSHARED is not set\n" >> .config
stage "minimize"
grep -q "^CONFIG_PACKAGE_libopenssl=y" .config 2>/dev/null || echo "CONFIG_PACKAGE_libopenssl=y" >> .config
grep -q "^CONFIG_OPENSSL_WITH_DTLS=y" .config 2>/dev/null || echo "CONFIG_OPENSSL_WITH_DTLS=y" >> .config
stage "config-set"
make defconfig >/sdk/build/openssl-defconfig.log 2>&1
grep -E "CONFIG_OPENSSL_WITH_DTLS|CONFIG_PACKAGE_libopenssl=" .config | tee -a /sdk/build/openssl-stage.txt
stage "compile-start"
make package/libs/openssl/{clean,compile} V=s >/sdk/build/openssl-compile.log 2>&1 || {
    tail -40 /sdk/build/openssl-compile.log
    stage "compile-FAILED"
    exit 1
}
stage "compile-done"
ls -la bin/packages/x86_64/base/ 2>/dev/null | grep -iE "openssl" | tee -a /sdk/build/openssl-stage.txt
