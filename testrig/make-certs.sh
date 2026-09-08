#!/usr/bin/env bash
# Sinh mot CA nho va chung chi cho hai Dovecot cua testrig.
#
# Vi sao phai co CA rieng chu khong dung cert tu ky: tool XAC THUC chung chi
# (imaplib.IMAP4_SSL dung context mac dinh cua Python), va imapsync cung vay.
# Cert tu ky se bi tu choi thang -- dung nhu no phai the. Muon test duong SSL
# cho ra hon thi phai dung mot CA that roi cho may tin no, giong het cach mot
# he thong noi bo van lam.
#
#   ./make-certs.sh          sinh vao testrig/certs/
#   ./make-certs.sh --trust  sinh xong cai luon CA vao trust store cua may nay
#
# Thu muc certs/ nam trong .gitignore: khoa rieng khong bao gio duoc commit.

set -euo pipefail
cd "$(dirname "$0")"

DIR=certs
DAYS=3650
mkdir -p "$DIR"

if [ -f "$DIR/ca.crt" ] && [ "${1:-}" != "--force" ] && [ "${1:-}" != "--trust" ]; then
  echo "Da co $DIR/ca.crt. Them --force de sinh lai."
  exit 0
fi

echo "==> CA"
openssl req -x509 -newkey rsa:2048 -sha256 -days "$DAYS" -nodes \
  -keyout "$DIR/ca.key" -out "$DIR/ca.crt" \
  -subj "/CN=migrate-mail testrig CA" 2>/dev/null

for side in src dst; do
  echo "==> chung chi cho $side ($side.test)"
  # SAN co ca ten mien lan 127.0.0.1: config cua rig tro thang vao loopback,
  # nhung dat ten mien vao de giong mot ca migrate that hon.
  cat > "$DIR/$side.ext" <<EXT
subjectAltName = DNS:$side.test, DNS:mm-$side, IP:127.0.0.1
basicConstraints = CA:FALSE
extendedKeyUsage = serverAuth
EXT
  openssl req -newkey rsa:2048 -nodes \
    -keyout "$DIR/$side.key" -out "$DIR/$side.csr" \
    -subj "/CN=$side.test" 2>/dev/null
  openssl x509 -req -in "$DIR/$side.csr" -CA "$DIR/ca.crt" -CAkey "$DIR/ca.key" \
    -CAcreateserial -out "$DIR/$side.crt" -days "$DAYS" -sha256 \
    -extfile "$DIR/$side.ext" 2>/dev/null
  rm -f "$DIR/$side.csr" "$DIR/$side.ext"
done

# Dovecot chay bang user root trong container roi ha quyen; khoa de 644 cho
# don gian vi day la rig vut di. Tren server that thi khoa phai 600.
chmod 644 "$DIR"/*.crt "$DIR"/*.key

echo
echo "Xong. Trong $DIR/:"
ls -1 "$DIR"

if [ "${1:-}" = "--trust" ]; then
  echo
  echo "==> cai CA vao trust store cua may nay"
  cp "$DIR/ca.crt" /usr/local/share/ca-certificates/migrate-mail-testrig.crt
  update-ca-certificates
  echo "Xong. Python va imapsync deu doc trust store nay."
fi
