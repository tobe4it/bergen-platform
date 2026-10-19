#!/bin/sh
# DSM Task Scheduler -> Triggered Task -> Boot-up; execute as root.
# Sends Magic Packets only. Never changes NAS/host network or firmware.
set -eu

# Fail closed unless a deliberate operation was selected.
# --check never sends packets and never sleeps/reconfigures anything.
case "${1:-}" in
    --check) MODE=check ;;
    --send) MODE=send ;;
    *)
        echo 'Usage: synology-venombox-wol-onboot.sh --check|--send' >&2
        exit 2
        ;;
esac

WAKE_IF=eth0
SYNONET=/usr/syno/sbin/synonet
MAC_FILE=/volume1/bergen-recovery/venombox-wol.mac

# DSM boot tasks can start before the data volume is ready.
# Waiting is permitted only in the explicitly approved send mode.
if [ "$MODE" = send ]; then
    delay=0
    while [ ! -r "$MAC_FILE" ] && [ "$delay" -lt 30 ]; do
        sleep 10
        delay=$((delay + 1))
    done
fi

if [ "$(id -u)" != "0" ]; then
    echo 'ERROR: run as root via DSM Task Scheduler' >&2
    exit 1
fi
if [ ! -x "$SYNONET" ] || [ ! -r "$MAC_FILE" ] ||
   [ ! -f "$MAC_FILE" ] || [ -L "$MAC_FILE" ]; then
    echo 'ERROR: synonet or protected regular MAC file unavailable' >&2
    exit 1
fi
if [ "$(wc -l < "$MAC_FILE")" -ne 1 ]; then
    echo 'ERROR: target MAC file must contain exactly one newline-terminated line' >&2
    exit 1
fi
TARGET_MAC=$(head -n 1 "$MAC_FILE")
if ! printf '%s\n' "$TARGET_MAC" | grep -Eiq '^([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}$'; then
    echo 'ERROR: invalid target MAC format' >&2
    exit 1
fi

if [ "$MODE" = check ]; then
    echo 'WOL_PREFLIGHT_OK; interface=eth0; packet_send=NONE; reboot=NONE'
    exit 0
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
