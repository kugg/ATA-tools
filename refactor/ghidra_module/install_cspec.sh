#!/usr/bin/env bash
# Install the corrected MIPS-X ABI compiler spec into the local Ghidra module.
# Dry-run by default; pass --apply to change the installed module.
set +x
umask 077

HERE="$(cd "$(dirname "$0")" && pwd)"
PRIMARY="${GHIDRA_MIPSX_MODULE:-/usr/local/Cellar/ghidra/12.1.3/libexec/Ghidra/Processors/MIPSX/data/languages}"
EXTENSION="${GHIDRA_MIPSX_EXTENSION:-$HOME/.config/ghidra/ghidra_12.1.3_PUBLIC/Extensions/MIPSX/data/languages}"
FILES="mipsx.cspec mipsx_be.slaspec mipsx_be.sla"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

MODULES="$PRIMARY"
[ -d "$EXTENSION" ] && MODULES="$MODULES $EXTENSION"

if [ "$1" != "--apply" ]; then
    log "DRY RUN: would install from $HERE into: $MODULES"
    log "DRY RUN: files: $FILES (existing files backed up once to *.pre-abi-backup)"
    log "re-run with --apply to perform the change"
    exit 0
fi

for MODULE in $MODULES; do
    [ -d "$MODULE" ] || { log "ERROR: module dir missing: $MODULE"; exit 1; }
    [ -w "$MODULE" ] || { log "ERROR: module dir not writable: $MODULE"; exit 1; }
    for name in $FILES; do
        src="$HERE/$name"
        dst="$MODULE/$name"
        backup="$MODULE/$name.pre-abi-backup"
        [ -f "$src" ] || { log "ERROR: source missing: $src"; exit 1; }
        if [ -f "$dst" ] && [ ! -f "$backup" ]; then
            cp -p "$dst" "$backup" || { log "ERROR: backup failed: $dst"; exit 1; }
            log "backed up $dst -> $backup"
        fi
        tmp="$(mktemp "$MODULE/.$name.XXXXXX")" || exit 1
        cp "$src" "$tmp" || { log "ERROR: staging failed: $src"; rm -f "$tmp"; exit 1; }
        chmod 0644 "$tmp"
        mv "$tmp" "$dst" || { log "ERROR: install failed: $dst"; exit 1; }
        log "installed $dst"
    done
done
log "done. rollback: for each file, cp -p <file>.pre-abi-backup <file>"
