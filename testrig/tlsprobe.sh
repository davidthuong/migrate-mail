#!/usr/bin/env bash
# Ma hoa dung chung chi cua ai? -- phep thu cho cau hoi do.
#
# `tls_verify` dat cuoc vao mot dieu chua ai kiem: rang bat doi chieu chung chi
# thi TEN HOST cung duoc kiem theo. Hai viec do khac nhau. Mot ke chen
# duoc vao duong truyen thuong co san chung chi that -- do CA cong cong ky, cho
# ten mien cua chinh no. Neu ta chi kiem "chung chi nay co hop le khong" ma
# khong kiem "no co phai cap cho dung host nay khong" thi chung chi do di qua,
# va mat khau -- voi auth = master la mat khau mo MOI hop thu -- di theo.
#
# Rig Docker o day khong tra loi duoc cau nay: chung chi cua no cap dung ten,
# nen ca hai cach kiem deu cho ket qua "chay duoc". Phai co mot chung chi do
# dung CA do ky nhung SAI TEN thi hai truong hop moi tach ra. Script nay dung
# dung mot cai nhu vay.
#
# Khong can Docker, khong can Dovecot, chay het trong ~10 giay:
#
#     ./tlsprobe.sh
#
# Can: openssl, perl co IO::Socket::SSL (imapsync bat buoc phai co), python3.
# Tren VPS da chay install.sh thi du ca ba.
#
# Ket qua mong doi -- chung chi SAI TEN phai bi tu choi o ca hai nua:
#
#     duong                          mong doi
#     imapsync --sslargs SSL_verify_mode=1   TU CHOI
#     imaplib + create_default_context       TU CHOI
#     ca hai khi tat doi chieu               ket noi duoc (chinh la lo hong)
#
# Exit 0 khi moi o khop mong doi, 1 khi co o lech.

set -euo pipefail

PORT_GOOD=14993
PORT_WRONG=14994

# Hai doan duoi cho chay duoc ca tren Git Bash cua may dev lan tren VPS; tren
# Linux ca hai deu vo hai.

# Thu chay that chu khong chi `command -v`: Windows co san mot 'python3' gia,
# no khong chay gi ca ma chi mo Microsoft Store.
PYTHON=
for cand in python3 python; do
  if "$cand" -c "import ssl" >/dev/null 2>&1; then PYTHON=$cand; break; fi
done
[ -n "$PYTHON" ] || { echo "khong tim thay python3 chay duoc" >&2; exit 1; }

# Python cua Windows khong mo duoc duong dan kieu /tmp/xxx cua msys.
py_path() { command -v cygpath >/dev/null 2>&1 && cygpath -w "$1" || echo "$1"; }

DIR=$(mktemp -d)
SERVERS=()
cleanup() {
  for pid in "${SERVERS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  rm -rf "$DIR"
}
trap cleanup EXIT

# --- chung chi ---------------------------------------------------------------
# CA rieng, dung mot lan roi vut. Khong dong vao trust store cua may: ca hai
# client duoi day deu duoc tro thang vao file CA nay.

# Ten chu the di qua file config chu khong qua -subj: tren Git Bash, msys thay
# mot doi so bat dau bang '/' la doi ngay thanh duong dan Windows, nen
# '-subj /CN=...' toi tay openssl thanh 'C:/Program Files/Git/CN=...'.
subj_cnf() {
  printf '[req]\nprompt = no\ndistinguished_name = dn\n[dn]\nCN = %s\n' "$1"
}

# CA phai co basicConstraints CA:TRUE. Khi tu dua -config vao thi openssl
# khong con them extension mac dinh nua, va mot "CA" thieu dong do se bi
# chinh no tu choi khi di xac thuc chung chi con.
printf '%s\n' \
  '[req]' \
  'prompt = no' \
  'distinguished_name = dn' \
  'x509_extensions = ca_ext' \
  '[dn]' \
  'CN = Postboat tlsprobe CA' \
  '[ca_ext]' \
  'basicConstraints = critical,CA:TRUE' \
  'keyUsage = critical,keyCertSign' > "$DIR/ca.cnf"
openssl req -x509 -newkey rsa:2048 -sha256 -days 1 -nodes \
  -config "$DIR/ca.cnf" -keyout "$DIR/ca.key" -out "$DIR/ca.crt" 2>/dev/null

gen_cert() {
  name=$1; cn=$2; san=$3
  subj_cnf "$cn" > "$DIR/$name.cnf"
  printf 'subjectAltName = %s\nbasicConstraints = CA:FALSE\nextendedKeyUsage = serverAuth\n' \
    "$san" > "$DIR/$name.ext"
  openssl req -new -newkey rsa:2048 -nodes -config "$DIR/$name.cnf" \
    -keyout "$DIR/$name.key" -out "$DIR/$name.csr" 2>/dev/null
  openssl x509 -req -in "$DIR/$name.csr" -CA "$DIR/ca.crt" -CAkey "$DIR/ca.key" \
    -CAcreateserial -out "$DIR/$name.crt" -days 1 -sha256 \
    -extfile "$DIR/$name.ext" 2>/dev/null
}

# good : cap cho dung cai client se goi toi (127.0.0.1)
# wrong: CUNG MOT CA ky, nhung cap cho ten khac -- chuoi chung chi hop le,
#        danh tinh thi khong. Day la ke chen duong truyen cam chung chi that.
gen_cert good  "127.0.0.1"     "IP:127.0.0.1"
gen_cert wrong "wrong.example" "DNS:wrong.example"

# --- hai client --------------------------------------------------------------
# Moi cai dung y het cach tool goi thu vien that, khong phai ban rut gon.

cat > "$DIR/client.pl" <<'PERL'
# Nua imapsync. Ba che do:
#   ssl-verify   = --ssl1 + --sslargs1 SSL_verify_mode=1   (duong tool dang di)
#   tls-verify   = --tls1 + --sslargs1 SSL_verify_mode=1   (set_tls cua imapsync
#                  KHONG co SSL_verifycn_scheme -- xem no co con kiem ten khong)
#   ssl-noverify = mac dinh cua imapsync, tuc la khong kiem gi
use strict;
use warnings;
use IO::Socket::SSL;

my ($port, $ca, $mode) = @ARGV;
my %args = (
    PeerHost        => '127.0.0.1',
    PeerPort        => $port,
    SSL_ca_file     => $ca,
    SSL_cipher_list => 'DEFAULT:!DH',
);
if    ($mode eq 'ssl-verify')   { $args{SSL_verify_mode} = 1;
                                  $args{SSL_verifycn_scheme} = 'imap' }
elsif ($mode eq 'tls-verify')   { $args{SSL_verify_mode} = 1 }
elsif ($mode eq 'ssl-noverify') { $args{SSL_verify_mode} = 0;
                                  $args{SSL_verifycn_scheme} = 'imap' }
else { die "che do la ssl-verify | tls-verify | ssl-noverify\n" }

if (IO::Socket::SSL->new(%args)) { print "OK\n" }
else { print "TU CHOI: " . ($SSL_ERROR || $! || 'khong ro') . "\n" }
PERL

cat > "$DIR/client.py" <<'PY'
# Nua Python cua tool -- giong het postboat/discover.py:ssl_context().
import socket
import ssl
import sys

port, ca, mode = int(sys.argv[1]), sys.argv[2], sys.argv[3]
ctx = ssl.create_default_context()
ctx.load_verify_locations(ca)
if mode == "py-noverify":
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
try:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
        with ctx.wrap_socket(raw, server_hostname="127.0.0.1"):
            print("OK")
except ssl.SSLError as e:
    print("TU CHOI: %s" % (e.reason or e))
except OSError as e:
    print("TU CHOI: %s" % e)
PY

# --- hai server TLS ----------------------------------------------------------

start_server() {
  cert=$1; port=$2
  openssl s_server -accept "$port" -cert "$DIR/$cert.crt" -key "$DIR/$cert.key" \
    -naccept 50 -quiet >/dev/null 2>&1 &
  SERVERS+=($!)
  for _ in $(seq 1 100); do
    if (exec 3<>/dev/tcp/127.0.0.1/"$port") 2>/dev/null; then exec 3<&- ; return 0; fi
  done
  echo "khong dung duoc server TLS o cong $port" >&2
  exit 1
}

start_server good  "$PORT_GOOD"
start_server wrong "$PORT_WRONG"

# --- chay va doi chieu mong doi ----------------------------------------------

FAILED=0

check() {
  label=$1; port=$2; mode=$3; want=$4   # want = OK | TU CHOI
  case "$mode" in
    py-*) got=$("$PYTHON" "$(py_path "$DIR/client.py")" "$port" \
                "$(py_path "$DIR/ca.crt")" "$mode") ;;
    *)    got=$(perl    "$DIR/client.pl" "$port" "$DIR/ca.crt" "$mode") ;;
  esac
  if [ "${got%%:*}" = "$want" ]; then
    printf '  [ OK ] %-28s %s\n' "$label" "$got"
  else
    printf '  [LECH] %-28s mong doi %s, nhan duoc %s\n' "$label" "$want" "$got"
    FAILED=1
  fi
}

echo
echo "=== chung chi cap dung ten (SAN = IP:127.0.0.1) -- phai chay duoc het ==="
check "imapsync --ssl  + verify"  "$PORT_GOOD" ssl-verify   "OK"
check "imapsync --tls  + verify"  "$PORT_GOOD" tls-verify   "OK"
check "imapsync khong kiem"       "$PORT_GOOD" ssl-noverify "OK"
check "imaplib + verify"          "$PORT_GOOD" py-verify    "OK"
check "imaplib khong kiem"        "$PORT_GOOD" py-noverify  "OK"

echo
echo "=== CUNG CA ky, nhung cap cho wrong.example -- day moi la phep thu ==="
check "imapsync --ssl  + verify"  "$PORT_WRONG" ssl-verify   "TU CHOI"
check "imapsync --tls  + verify"  "$PORT_WRONG" tls-verify   "TU CHOI"
check "imapsync khong kiem"       "$PORT_WRONG" ssl-noverify "OK"
check "imaplib + verify"          "$PORT_WRONG" py-verify    "TU CHOI"
check "imaplib khong kiem"        "$PORT_WRONG" py-noverify  "OK"

echo
if [ "$FAILED" -eq 0 ]; then
  echo "Moi o khop mong doi: bat doi chieu thi chung chi sai ten bi chan o ca"
  echo "hai nua, tat doi chieu thi no di qua."
  exit 0
fi
echo "CO O LECH -- doc lai bang tren truoc khi tin vao tls_verify."
exit 1
