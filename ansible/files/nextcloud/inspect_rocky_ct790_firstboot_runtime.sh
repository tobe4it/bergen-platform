#!/bin/sh
# In-guest bounded identity and interface probe for the approved offline CT790.
# Run only via pct exec 790 AFTER an independently approved pct start 790.
# No files are written by this script; systemd boot itself may write to rootfs.
set -eu

test -r /usr/lib/os-release
id_count=0
version_count=0
while IFS= read -r line || test -n "$line"; do
  case "$line" in
    'ID="rocky"') id_count=$((id_count + 1)) ;;
    'VERSION_ID="9.8"') version_count=$((version_count + 1)) ;;
    ID=*|VERSION_ID=*) exit 71 ;;
  esac
done < /usr/lib/os-release
test "$id_count" -eq 1
test "$version_count" -eq 1

test -r /proc/1/comm
IFS= read -r pid1 < /proc/1/comm || test -n "$pid1"
test "$pid1" = systemd

test -r /proc/sys/kernel/hostname
IFS= read -r guest_name < /proc/sys/kernel/hostname || test -n "$guest_name"
test "$guest_name" = rocky9-base-790

test -L /sys/class/net/lo
extra_interfaces=0
for dev in /sys/class/net/*; do
  test -L "$dev" || continue
  case "$dev" in
    */lo) : ;;
    *) extra_interfaces=$((extra_interfaces + 1)) ;;
  esac
done
test "$extra_interfaces" -eq 0

test -r /proc/1/uid_map
IFS=' ' read -r inner_uid outer_uid span < /proc/1/uid_map
test "$inner_uid" = 0
case "$outer_uid" in
  ''|*[!0-9]*) exit 72 ;;
esac
case "$span" in
  ''|*[!0-9]*) exit 73 ;;
esac
test "$outer_uid" -ge 65536
test "$span" -ge 65536

printf '%s\n' 'ROCKY_9_8_CT790_RUNTIME_IDENTITY=VERIFIED'
printf '%s\n' 'PID1=systemd'
printf '%s\n' 'NON_LOOPBACK_DEVICES=0'
printf '%s\n' 'GUEST_IDMAP_NONIDENTITY=YES'
printf '%s\n' 'RUNTIME_GUEST_WRITE_OPERATIONS=NONE_BY_PROBE'
