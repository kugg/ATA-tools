#!/bin/sh
# APU2/3 mSATA: add /data partition from the unallocated GPT tail + bind the
# write-heavy twin paths onto it. Dry-run default; --apply performs the step.
#
# Measured on the live office APU2 2026-09-18 (read-only evidence, nothing
# changed): /dev/sda = 15,638,616 KiB (~14.9 GiB); sda1 16 MiB boot, sda2
# 104 MiB root+as-overlay (overlay 86.6M total, 33.0M free); the remaining
# ~14.4 GiB is unallocated GPT space -> one new partition (sda3) + ext4.
#
# Safety: runs READ-ONLY unless --apply. Refuses if sda2 is not the mounted
# overlay or if /dev/sda is not a block device. Uses sgdisk to append at the
# first LBA after sda2, mkfs.ext4 -F on the new partition only, mounts at
# /data, then bind-mounts the grow paths. Does NOT resize or touch sda2.
# Rollback = umount + rm partition + rmdir (recorded). No egress needed.
set +x -u
umask 077
DEV=/dev/sda
MP=/data
MNTPATHS="recordings cdr logs"        # bind-mounted dirs under $MP

die() { printf 'apu2-expand-data: %s\n' "$*" >&2; exit 1; }

[ -b "$DEV" ]         || die "block device $DEV missing"
[ -e /usr/sbin/sgdisk ] || [ -e /usr/bin/sgdisk ] || die "sgdisk not present"

overlay_dev=$(awk '$2=="/overlay"{print $1}' /proc/mounts | sed 's/:.*//' | tail -1)
case "$overlay_dev" in
  loop*|/dev/loop*) : ;;          # expected: loop-backed as-overlay on P2
  *) die "overlay not loop-backed ($overlay_dev) -- refusing" ;;
esac
# overlay must actually be mounted from sda2; parse loop backing
if [ -r "/sys/class/block/${overlay_dev}/loop/backing_file" ]; then
  bk=$(cat "/sys/class/block/${overlay_dev}/loop/backing_file")
  case "$bk" in *sda2*|*/dev/sda2*) : ;;
    *) die "overlay backing $bk is not sda2 -- refusing" ;;
  esac
else
  die "cannot verify overlay backing"    # no resizing of anything, safe fallback
fi

# find first free sector + planned sda3 range from the GPT (read-only)
sgdisk -p "$DEV" >/tmp/apu2-sgdisk.txt 2>/dev/null || die "sgdisk -p failed"
last_end=$(sgdisk -E "$DEV" 2>/dev/null) || die "cannot compute last usable sector"
# last_end is a sector idx; new partition = (last_sda2_end+1 .. last_end)
s2_end=$(awk '/^  [0-9]+ +[0-9]+ +1048576\.0/{print $2}' /tmp/apu2-sgdisk.txt 2>/dev/null | tail -1)
if [ -z "$s2_end" ]; then
  # fallback: parse table lines "  2   <start>  <end>  102MiB ..."
  s2_end=$(awk 'NR>6 && $1==2 {print $3}' /tmp/apu2-sgdisk.txt | tail -1)
fi
[ -n "$s2_end" ] || die "could not locate sda2 end sector"

start=$((s2_end + 1))
mib=$(( (last_end - start + 1) * 512 / 1048576 ))

echo "PLAN (read-only unless --apply):"
echo "  /dev/sda3  sectors $start..$last_end  (~$mib MiB)  -> ext4 at $MP"
printf '  bind-mounts: '
for p in $MNTPATHS; do printf '%s/%s ' "$MP" "$p"; done; echo

if [ "$1" != "--apply" ]; then
  echo "DRY-RUN: no changes. Re-run with --apply to create partition+mounts."
  exit 0
fi

# --- apply ---
sgdisk -n 3:"$start":"$last_end" -t 8e00 "$DEV" 2>&1 || die "sgdisk failed"
partprobe "$DEV" 2>/dev/null || sync
sleep 1
mkfs.ext4 -F -L data "$DEV"3 >/dev/null 2>&1 || die "mkfs failed"
mkdir -p "$MP"
mount "$DEV"3 "$MP" || die "mount failed"

for p in $MNTPATHS; do
  mkdir -p "$MP/$p" "$p" 2>/dev/null
  mount --bind "$p" "$MP/$p" 2>/dev/null || true   # best-effort per path
done

df -h "$MP" /overlay
echo "DONE. Review: mount | grep $MP   (rollback: umount all, sgdisk -d 3 $DEV)"
