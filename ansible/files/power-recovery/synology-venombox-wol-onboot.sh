#!/bin/sh
# DSM Task Scheduler -> Triggered Task -> Boot-up; execute as root.
# Sends Magic Packets only. Never changes NAS/host network or firmware.
set -eu

WAKE_IF=eth0
SYNONET=/usr/syno/sbin/synonet
MAC_FILE=/volume1/bergen-recovery/venombox-wol.mac

if [ "$(id -u)" != "0" ]; then
    echo 'ERROR: run as root via DSM Task Scheduler' >&2
    exit 1
fi
if [ ! -x "$SYNONET" ] || [ ! -r "$MAC_FILE" ]; then
    echo 'ERROR: synonet or protected MAC file unavailable' >&2
    exit 1
fi
TARGET_MAC=$(head -n 1 "$MAC_FILE")
if ! printf '%s\n' "$TARGET_MAC" | grep -Eiq '^([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}$'; then
    echo 'ERROR: invalid target MAC format' >&2
    exit 1
fi

# A NAS may complete boot before the switch has recovered from an outage.
try=0
while [ "$try" -lt 30 ]; do
    if [ -r "/sys/class/net/$WAKE_IF/carrier" ] &&
       [ "$(cat "/sys/class/net/$WAKE_IF/carrier")" = '1' ]; then
        break
    fi
    try=$((try + 1))
    sleep 10
done
if [ "$try" -ge 30 ]; then
    echo 'ERROR: eth0 never acquired physical carrier' >&2
    exit 1
fi

# Allow network startup, then send bounded repeats.
sleep 60
sent=0
try=1
while [ "$try" -le 12 ]; do
    if "$SYNONET" --wake "$TARGET_MAC" "$WAKE_IF"; then
        sent=$((sent + 1))
        echo "Magic Packet send requested ($try/12)"
    else
        echo "WARNING: synonet send failed ($try/12)" >&2
    fi
    if [ "$try" -lt 12 ]; then
        sleep 30
    fi
    try=$((try + 1))
done
[ "$sent" -gt 0 ] || { echo 'ERROR: every synonet attempt failed' >&2; exit 1; }
echo 'WOL_BOOT_SEND_COMPLETED; host wake not independently verified'
