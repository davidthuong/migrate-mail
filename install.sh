#!/usr/bin/env bash
#
# Cai imapsync va cac module Perl no can, tren VPS Linux.
# Chay voi quyen root:   sudo ./install.sh
#
# Script KHONG giu danh sach module cung. No tai imapsync ve truoc, doc cac
# dong `use`/`require` ngay trong file do, roi cai dung nhung gi ban imapsync
# nay can. Danh sach cung se luon lech theo thoi gian; doc tu nguon thi khong.
#
# Bien moi truong tuy chon:
#   IMAPSYNC_REF=v2.290   phien ban imapsync muon lay (mac dinh: master)
#   PREFIX=/usr/local/bin noi dat file imapsync
#
set -euo pipefail

IMAPSYNC_REF="${IMAPSYNC_REF:-master}"
PREFIX="${PREFIX:-/usr/local/bin}"
SRC_URL="https://raw.githubusercontent.com/imapsync/imapsync/${IMAPSYNC_REF}/imapsync"
MAX_FIX_ROUNDS=15

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[canh bao]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[loi]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "can chay bang root: sudo ./install.sh"

DISTRO=unknown
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO="${ID_LIKE:-${ID:-unknown}}"
fi
log "He dieu hanh: ${PRETTY_NAME:-khong ro} (ho: ${DISTRO})"

IS_DEBIAN=0
case "$DISTRO" in
    *debian*|*ubuntu*) IS_DEBIAN=1 ;;
esac

# --- Buoc 1: cai nen -------------------------------------------------------
# Chi cai perl, trinh bien dich (nhieu module Perl la XS phai compile), va
# thu vien -dev ma cac module do can. Module Perl de buoc sau lo.
install_base_debian() {
    log "Cai goi nen bang apt-get..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        perl perl-modules make gcc curl ca-certificates cpanminus \
        libssl-dev zlib1g-dev pkg-config >/dev/null
}

install_base_rhel() {
    log "Cai goi nen bang dnf/yum..."
    PKG=dnf; command -v dnf >/dev/null 2>&1 || PKG=yum
    $PKG install -y epel-release >/dev/null 2>&1 || true
    $PKG install -y perl perl-core perl-App-cpanminus make gcc curl \
        openssl-devel zlib-devel >/dev/null
}

if [ "$IS_DEBIAN" -eq 1 ]; then
    install_base_debian
else
    case "$DISTRO" in
        *rhel*|*fedora*|*centos*) install_base_rhel ;;
        *) warn "khong nhan ra ban phan phoi, thu theo huong Debian"
           install_base_debian || die "khong cai duoc goi nen, cai thu cong roi chay lai" ;;
    esac
fi

command -v cpanm >/dev/null 2>&1 || {
    log "Cai cpanminus..."
    curl -fsSL https://cpanmin.us | perl - --sudo App::cpanminus
}

# --- Buoc 2: tai imapsync --------------------------------------------------
log "Tai imapsync (${IMAPSYNC_REF}) tu GitHub..."
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -fsSL "$SRC_URL" -o "$TMP" || die "khong tai duoc $SRC_URL"
head -1 "$TMP" | grep -q perl || die "file tai ve khong phai script Perl, kiem tra lai IMAPSYNC_REF"
install -m 0755 "$TMP" "$PREFIX/imapsync"
log "Da dat: $PREFIX/imapsync"

# --- Buoc 3: doc danh sach module ngay trong file imapsync -----------------
# Loc cac dong dang "use Foo::Bar;" / "require Foo::Bar;". Bo qua pragma
# (viet thuong nhu strict, warnings) vi mau chi bat ten bat dau bang chu hoa.
derive_modules() {
    grep -hoE "^[[:space:]]*(use|require)[[:space:]]+[A-Z][A-Za-z0-9_:]*" "$1" \
        | sed -E 's/^[[:space:]]*(use|require)[[:space:]]+//' \
        | sort -u
}

# Doi ten module sang ten goi Debian theo quy uoc: Foo::Bar -> libfoo-bar-perl.
# Khong phai module nao cung khop (Digest::HMAC_SHA1 nam trong libdigest-hmac-perl),
# nen ham nay chi la duong tat -- truot thi da co cpanm lo.
apt_try() {
    [ "$IS_DEBIAN" -eq 1 ] || return 1
    local pkg
    pkg="lib$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/::/-/g' | tr '_' '-')-perl"
    apt-cache show "$pkg" >/dev/null 2>&1 || return 1
    apt-get install -y --no-install-recommends "$pkg" >/dev/null 2>&1
}

has_module() { perl -M"$1" -e1 >/dev/null 2>&1; }

install_module() {
    local mod="$1"
    has_module "$mod" && return 0
    apt_try "$mod" && has_module "$mod" && return 0
    cpanm --notest --quiet "$mod" >/dev/null 2>&1 || true
    has_module "$mod"
}

log "Doc danh sach module tu chinh file imapsync..."
ALL_MODULES="$(derive_modules "$PREFIX/imapsync")"
TOTAL="$(printf '%s\n' "$ALL_MODULES" | grep -c . || true)"

MISSING=()
while IFS= read -r mod; do
    [ -n "$mod" ] || continue
    has_module "$mod" || MISSING+=("$mod")
done <<< "$ALL_MODULES"

log "imapsync khai bao $TOTAL module, thieu ${#MISSING[@]}."

if [ "${#MISSING[@]}" -gt 0 ]; then
    for mod in "${MISSING[@]}"; do
        printf '    %-34s ' "$mod"
        if install_module "$mod"; then
            printf 'ok\n'
        else
            printf 'CHUA CAI DUOC\n'
        fi
    done
fi

# --- Buoc 4: chay thu, va tu sua theo dung loi imapsync bao ----------------
# Day moi la kiem tra that. Buoc tren co the con sot module duoc nap gian tiep
# (module nay keo module kia). imapsync tu noi no thieu gi -- cu doc dong
# "Can't locate Foo/Bar.pm" roi cai dung cai do, lap lai cho den khi chay duoc.
log "Chay thu imapsync va tu bu module con thieu..."
OK=0
for round in $(seq 1 "$MAX_FIX_ROUNDS"); do
    if ERR_OUT="$("$PREFIX/imapsync" --version 2>&1)"; then
        OK=1
        break
    fi
    # Luu y: dau phan cach cua Perl la "::" chu khong phai ":".
    # Dung sed thay cho tr -- tr chi doi duoc 1 ky tu sang 1 ky tu.
    MOD="$(printf '%s' "$ERR_OUT" \
        | sed -nE "s#.*Can't locate ([A-Za-z0-9_/]+)\.pm.*#\1#p" \
        | head -1 | sed 's#/#::#g')"
    if [ -z "$MOD" ]; then
        warn "imapsync loi nhung khong phai do thieu module:"
        printf '%s\n' "$ERR_OUT" | head -20
        break
    fi
    log "  vong $round: thieu $MOD, dang cai..."
    if ! install_module "$MOD"; then
        die "khong cai duoc $MOD. Thu thu cong: cpanm $MOD"
    fi
done

if [ "$OK" -ne 1 ]; then
    printf '%s\n' "${ERR_OUT:-}" | head -20
    die "imapsync van chua chay duoc sau $MAX_FIX_ROUNDS vong."
fi

log "imapsync chay duoc: $("$PREFIX/imapsync" --version 2>&1 | head -1)"

echo
log "Xong. Buoc tiep theo:"
echo "    cp config.example.ini config.ini   && vi config.ini"
echo "    cp users.example.csv  users.csv    && vi users.csv && chmod 600 users.csv"
echo "    python3 mm.py doctor"
