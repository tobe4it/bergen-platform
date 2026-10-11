#!/usr/bin/env bash
# Invoked over verified SSH stdin. No private key is emitted or stored in logs.
set -Eeuo pipefail
umask 077

stage=$1
expected_new=$2
expected_old=$3
fqdn=$4
live_cert=$5
live_key=$6
ports=$7
backup=''
activation_started=0

fingerprint() {
  openssl x509 -in "$1" -noout -fingerprint -sha256 |
    awk -F= '{gsub(/:/,"",$2); print tolower($2)}'
}

pub_digest() {
  if [[ $1 == key ]]; then
    openssl pkey -in "$2" -pubout -outform DER | openssl dgst -sha256
  else
    openssl x509 -in "$2" -noout -pubkey |
      openssl pkey -pubin -outform DER | openssl dgst -sha256
  fi
}

check_live() {
  systemctl is-active --quiet postfix
  systemctl is-active --quiet dovecot
  local port output leaf
  IFS=',' read -r -a port_list <<< "$ports"
  for port in "${port_list[@]}"; do
    local args=(-connect "127.0.0.1:$port" -servername "$fqdn"
                -verify_hostname "$fqdn" -verify_return_error)
    if [[ "$port" == 587 ]]; then args=(-starttls smtp "${args[@]}"); fi
    output=$(timeout 20 openssl s_client "${args[@]}" </dev/null 2>&1)
    grep -Fq 'Verify return code: 0 (ok)' <<< "$output"
    leaf=$(printf '%s\n' "$output" | openssl x509 -noout -fingerprint -sha256 |
           awk -F= '{gsub(/:/,"",$2); print tolower($2)}')
    test "$leaf" = "$expected_new"
    echo "PASS: TLS listener $port"
  done
}

rollback() {
  local rc=$?
  trap - EXIT HUP INT TERM
  if ((rc != 0 && activation_started == 1)); then
    set +e
    echo 'ERROR: Activation failed; restoring previous key pair' >&2
    systemctl stop dovecot postfix >/dev/null 2>&1
    install -o root -g root -m 0644 "$backup/fullchain.pem" "$live_cert"
    local cert_rc=$?
    install -o root -g root -m 0600 "$backup/privkey.pem" "$live_key"
    local key_rc=$?
    systemctl start postfix dovecot >/dev/null 2>&1
    local restart_rc=$?
    if ((cert_rc == 0 && key_rc == 0 && restart_rc == 0)) &&
       systemctl is-active --quiet postfix && systemctl is-active --quiet dovecot; then
      echo "ROLLBACK_OK: Previous certificate restored; backup $backup" >&2
    else
      echo "ROLLBACK_FAILED: Manual intervention required; backup $backup" >&2
    fi
  fi
  exit "$rc"
}
trap rollback EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

[[ "$expected_new" =~ ^[a-f0-9]{64}$ ]]
[[ "$expected_old" =~ ^[a-f0-9]{64}$ ]]
[[ "$fqdn" =~ ^[a-zA-Z0-9.-]+$ ]]
[[ "$live_cert" == /* && "$live_key" == /* ]]
[[ "$ports" =~ ^(993|587|465)(,(993|587|465))*$ ]]

exec 9>/run/lock/mail-tls-rotation.lock
flock -n 9 || { echo 'Another certificate rotation is active' >&2; exit 1; }

test -f "$live_cert" && test ! -L "$live_cert"
test -f "$live_key" && test ! -L "$live_key"
test "$(fingerprint "$live_cert")" = "$expected_old"
test "$(pub_digest cert "$live_cert")" = "$(pub_digest key "$live_key")"
test "$(postconf -h smtpd_tls_cert_file)" = "$live_cert"
test "$(postconf -h smtpd_tls_key_file)" = "$live_key"
test "$(doveconf -h ssl_server/cert_file)" = "$live_cert"
test "$(doveconf -h ssl_server/key_file)" = "$live_key"
test "$(postconf -h myhostname)" = "$fqdn"

if [[ "$stage" == CHECK_ONLY ]]; then
  test "$expected_new" = "$expected_old"
  check_live
  echo 'NO_CHANGE: Installed certificate and all TLS listeners verified'
  exit 0
fi

[[ "$stage" =~ ^/etc/ssl/private/\.mail-tls-stage\.[A-Za-z0-9]{8}$ ]]
test -d "$stage" && test ! -L "$stage"
test "$(stat -c %a "$stage")" = 700
test "$(stat -c %u "$stage")" = 0
for f in "$stage/fullchain.pem" "$stage/privkey.pem"; do
  test -f "$f" && test ! -L "$f"
  test "$(stat -c %u "$f")" = 0
  test "$(stat -c %a "$f")" = 600
done

test "$(fingerprint "$stage/fullchain.pem")" = "$expected_new"
test "$(pub_digest cert "$stage/fullchain.pem")" = "$(pub_digest key "$stage/privkey.pem")"
openssl x509 -in "$stage/fullchain.pem" -noout -checkend 2592000
openssl x509 -in "$stage/fullchain.pem" -noout -checkhost "$fqdn"
openssl verify -purpose sslserver -verify_hostname "$fqdn" \
  -untrusted "$stage/fullchain.pem" "$stage/fullchain.pem"

systemctl is-active --quiet postfix
systemctl is-active --quiet dovecot

backup=$(mktemp -d /etc/ssl/private/.mail-tls-rollback.XXXXXXXX)
install -o root -g root -m 0600 "$live_cert" "$backup/fullchain.pem"
install -o root -g root -m 0600 "$live_key" "$backup/privkey.pem"
echo 'PASS: Validated staged certificate, private key and protected rollback copy'

activation_started=1
systemctl stop dovecot postfix
! systemctl is-active --quiet dovecot
! systemctl is-active --quiet postfix
install -o root -g root -m 0644 "$stage/fullchain.pem" "$live_cert"
install -o root -g root -m 0600 "$stage/privkey.pem" "$live_key"
postfix check >/dev/null
doveconf -n >/dev/null
systemctl start postfix dovecot
check_live

echo "ROTATED: Certificate active and TLS verified; rollback preserved: $backup"
