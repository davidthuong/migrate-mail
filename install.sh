#!/usr/bin/env bash
#
# Cai imapsync va cac module Perl no can, tren VPS Linux.
# Chay voi quyen root:   sudo ./install.sh
#
# Bien moi truong tuy chon:
#   IMAPSYNC_REF=v2.290   phien ban imapsync muon lay (mac dinh: master)
#   PREFIX=/usr/local/bin noi dat file imapsync
#
set -euo pipefail

IMAPSYNC_REF="${IMAPSYNC_REF:-master}"
PREFIX="${PREFIX:-/usr/local/bin}"
SRC_URL="https://raw.githubusercontent.com/imapsync/imapsync/${IMAPSYNC_REF}/imapsync"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[canh bao]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[loi]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "can chay bang root: sudo ./install.sh"

# --- Nhan dien ban phan phoi ------------------------------------------------
DISTRO=unknown
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO="${ID_LIKE:-${ID:-unknown}}"
fi
log "He dieu hanh: ${PRETTY_NAME:-khong ro} (ho: ${DISTRO})"

# Danh sach module Perl imapsync can. Ten CPAN dung cho ca hai nhanh cai dat.
CPAN_MODULES=(
    Authen::NTLM
    Crypt::OpenSSL::RSA
    Data::Uniqid
    Digest::HMAC
    Digest::MD5
    Encode::IMAPUTF7
    File::Copy::Recursive
    IO::Socket::INET6
    IO::Socket::SSL
    IO::Tee
    JSON::WebToken
    Mail::IMAPClient
    Net::SSLeay
    Readonly
    Regexp::Common
    Sys::MemInfo
    Term::ReadKey
    Test::MockObject
    Unicode::String
    URI::Escape
)

install_debian() {
    log "Cai goi bang apt-get..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    # Cai tu kho phan phoi truoc: nhanh hon va co san ban da vá bao mat.
    # '|| true' vi ten goi khac nhau chut giua cac ban Debian/Ubuntu.
    apt-get install -y --no-install-recommends \
        perl make gcc curl ca-certificates cpanminus \
        libauthen-ntlm-perl libcrypt-openssl-rsa-perl libdata-uniqid-perl \
        libdigest-hmac-perl libencode-imaputf7-perl libfile-copy-recursive-perl \
        libio-socket-inet6-perl libio-socket-ssl-perl libio-tee-perl \
        libjson-webtoken-perl libmail-imapclient-perl libnet-ssleay-perl \
        libreadonly-perl libregexp-common-perl libsys-meminfo-perl \
        libterm-readkey-perl libtest-mockobject-perl libunicode-string-perl \
        liburi-perl libwww-perl libparse-recdescent-perl >/dev/null || \
        warn "mot vai goi apt khong cai duoc, se bu bang cpanm o buoc sau"
}

install_rhel() {
    log "Cai goi bang dnf/yum..."
    PKG=dnf; command -v dnf >/dev/null 2>&1 || PKG=yum
    $PKG install -y epel-release >/dev/null 2>&1 || true
    $PKG install -y perl perl-App-cpanminus perl-core make gcc curl \
        openssl-devel perl-IO-Socket-SSL perl-Mail-IMAPClient \
        perl-Digest-HMAC perl-URI perl-libwww-perl >/dev/null || \
        warn "mot vai goi khong cai duoc, se bu bang cpanm o buoc sau"
}

case "$DISTRO" in
    *debian*|*ubuntu*) install_debian ;;
    *rhel*|*fedora*|*centos*) install_rhel ;;
    *)
        warn "khong nhan ra ban phan phoi, thu cai theo huong Debian"
        install_debian || die "khong cai duoc goi he thong, cai thu cong roi chay lai"
        ;;
esac

# --- Bu cac module con thieu bang cpanm --------------------------------------
command -v cpanm >/dev/null 2>&1 || {
    log "Cai cpanminus..."
    curl -fsSL https://cpanmin.us | perl - --sudo App::cpanminus
}

MISSING=()
for m in "${CPAN_MODULES[@]}"; do
    perl -M"$m" -e1 >/dev/null 2>&1 || MISSING+=("$m")
done

if [ "${#MISSING[@]}" -gt 0 ]; then
    log "Con thieu ${#MISSING[@]} module Perl, cai bang cpanm: ${MISSING[*]}"
    cpanm --notest --quiet "${MISSING[@]}" || \
        warn "cpanm bao loi o mot vai module -- xem ky output tren, co the van chay duoc"
else
    log "Du module Perl."
fi

# --- Lay imapsync ------------------------------------------------------------
log "Tai imapsync (${IMAPSYNC_REF}) tu GitHub..."
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -fsSL "$SRC_URL" -o "$TMP" || die "khong tai duoc $SRC_URL"
head -1 "$TMP" | grep -q perl || die "file tai ve khong phai script Perl, kiem tra lai IMAPSYNC_REF"

install -m 0755 "$TMP" "$PREFIX/imapsync"
log "Da dat: $PREFIX/imapsync"

# --- Kiem tra ----------------------------------------------------------------
if "$PREFIX/imapsync" --version >/dev/null 2>&1; then
    log "imapsync chay duoc: $("$PREFIX/imapsync" --version 2>&1 | head -1)"
else
    warn "imapsync chua chay duoc. Output loi:"
    "$PREFIX/imapsync" --version 2>&1 | head -20 || true
    die "thuong la do thieu module Perl -- doc dong 'Can't locate ... .pm' o tren roi cpanm cai module do"
fi

echo
log "Xong. Buoc tiep theo:"
echo "    cp config.example.ini config.ini   && vi config.ini"
echo "    cp users.example.csv  users.csv    && vi users.csv && chmod 600 users.csv"
echo "    python3 mm.py doctor"
