# -*- coding: utf-8 -*-
"""Doc danh sach mailbox do admin ben nguon xuat ra -> dung users.csv.

Vi sao can lop nay: voi mot tenant 200 mailbox, go tay 200 dong users.csv la
cho de sai nhat trong ca cuoc migrate. Sai mot ky tu trong dia chi thi mailbox
do im lang khong duoc chuyen, va thuong khong ai phat hien ra cho den sau
cutover. Danh sach dung phai lay tu chinh he thong nguon:

    Get-Mailbox -ResultSize Unlimited |
      Select-Object PrimarySmtpAddress,DisplayName,RecipientTypeDetails,ArchiveStatus |
      Export-Csv -NoTypeInformation -Encoding UTF8 mailboxes.csv

Nhung khong trong doi duoc rang file nhan ve dung dinh dang do. Ca nam kieu
duoi day deu tung gap, va deu doc duoc:

  - Export-Csv cua PowerShell 5.1 khi thieu -NoTypeInformation: dong dau la
    "#TYPE System.Management.Automation.PSCustomObject".
  - Out-File / `>` cua PowerShell 5.1: file UTF-16LE. Doc bang UTF-8 khong bao
    loi ma ra mot dong day ky tu NUL -- kieu hong im lang nhat.
  - Danh sach dia chi tho, moi dong mot cai (Select -ExpandProperty).
  - Cot dat ten khac: EmailAddress, UserPrincipalName, WindowsEmailAddress.
  - Export-Csv -UseCulture o locale chau Au: dau phan cach la ';'.

Ba viec lop nay lam ma cat/paste khong lam duoc:

1. Bo loai mailbox khong chua mail. Room/Equipment chi co lich, Discovery va
   Arbitration la hop thu he thong, Microsoft 365 Group khong vao duoc bang
   IMAP. Chep chung sang chi de lai mot dong loi trong bao cao va mot mailbox
   rong ben dich.
2. Chi bo nhung loai BIET chac la khong chua mail, con lai giu het. Bo nham
   mot mailbox that thi khong ai thay; giu nham mot mailbox rong thi preflight
   bao ngay o buoc sau. Nen khi gap loai la, giu lai va noi ra.
3. Bao truoc mailbox nao co Online Archive. Archive la mailbox rieng, khong co
   duong IMAP -- doc duoc con so nay TRUOC khi chay la co hoi duy nhat de noi
   voi khach hang, thay vi de ho tu phat hien sau cutover.
"""

from __future__ import annotations

import codecs
import csv
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .providers import fold
from .users import COLUMNS


class MailboxListError(ValueError):
    """File danh sach mailbox khong doc duoc. Ke thua ValueError de main() in
    ra mot cau thay vi nem traceback."""


# Ten cot chua dia chi, xep theo do uu tien. PrimarySmtpAddress la thu dung:
# UserPrincipalName co the khac dia chi mail that, con EmailAddresses la cot
# nhieu gia tri nen chi lay duoc cai dau tien -> de sau cung.
ADDRESS_COLUMNS = (
    "primarysmtpaddress", "emailaddress", "windowsemailaddress", "smtpaddress",
    "mail", "userprincipalname", "address", "diachi", "emailaddresses",
)
NAME_COLUMNS = ("displayname", "name", "ten", "hoten")
TYPE_COLUMNS = ("recipienttypedetails", "recipienttype", "mailboxtype", "type", "loai")
ARCHIVE_COLUMNS = ("archivestatus", "archivestate", "archiveguid", "archivedatabase")

# {RecipientTypeDetails da fold: ly do bo}. Chi liet ke loai KHONG chua mail.
SKIP_TYPES: Dict[str, str] = {
    "roommailbox": "phong hop - chi co lich, khong co mail",
    "equipmentmailbox": "thiet bi - chi co lich, khong co mail",
    "schedulingmailbox": "hop thu dat cho - chi co lich",
    "discoverymailbox": "hop thu he thong cua eDiscovery",
    "arbitrationmailbox": "hop thu he thong cua Exchange (arbitration)",
    "auditlogmailbox": "hop thu he thong luu audit log",
    "supervisoryreviewpolicymailbox": "hop thu he thong cua policy",
    "monitoringmailbox": "hop thu he thong theo doi cua Exchange",
    "groupmailbox": "Microsoft 365 Group - IMAP khong vao duoc",
    "teammailbox": "Site Mailbox cua SharePoint - IMAP khong vao duoc",
    "publicfoldermailbox": "public folder - IMAP khong voi den duoc",
}

# Tim dia chi trong mot o. Dung search chu khong match ca o, vi o co the la
# "An Nguyen <an@cu.com>" hoac "SMTP:an@cu.com" -- dau ':' va '<' khong nam
# trong lop ky tu nen chi phan dia chi duoc lay ra.
_EMAIL = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

_DELIMS = (",", ";", "\t")


@dataclass
class Mailbox:
    address: str
    name: str = ""
    kind: str = ""          # RecipientTypeDetails nguyen van, de in ra cho nguoi doc
    archive: bool = False
    row: int = 0            # dong trong file nguon, de chi cho nguoi dung sua


@dataclass
class Parsed:
    mailboxes: List[Mailbox] = field(default_factory=list)
    # (dia_chi_hoac_mo_ta, ly_do) -- luon in ra het, khong an dong nao.
    skipped: List[Tuple[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    address_column: str = ""
    rows_read: int = 0

    @property
    def archived(self) -> List[Mailbox]:
        return [m for m in self.mailboxes if m.archive]

    def kind_counts(self) -> List[Tuple[str, int]]:
        """So mailbox theo tung loai, nhieu nhat truoc."""
        counts: Dict[str, int] = {}
        for m in self.mailboxes:
            key = m.kind.strip() or "(khong ro loai)"
            counts[key] = counts.get(key, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))


def decode(raw: bytes) -> str:
    """Doc file bat ke PowerShell da ghi bang bang ma nao.

    Thu tu kiem tra co y: BOM cua UTF-16LE (ff fe) la tien to cua BOM UTF-32LE
    (ff fe 00 00), nen phai xet UTF-32 truoc -- du PowerShell khong ghi UTF-32
    thi cung khong mat gi.
    """
    for bom, enc in ((codecs.BOM_UTF8, "utf-8-sig"),
                     (codecs.BOM_UTF32_LE, "utf-32"),
                     (codecs.BOM_UTF32_BE, "utf-32"),
                     (codecs.BOM_UTF16_LE, "utf-16"),
                     (codecs.BOM_UTF16_BE, "utf-16")):
        if raw.startswith(bom):
            return raw.decode(enc)
    if b"\x00" in raw[:400]:
        # UTF-16LE khong co BOM: `>` cua PowerShell 5.1 ghi kieu nay. Doc bang
        # utf-8 se "thanh cong" nhung moi ky tu thu hai la NUL.
        return raw.decode("utf-16-le", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # Export-Csv mac dinh cua PowerShell 5.1 la ASCII; ai doi -Encoding
        # sang Default thi ra codepage cua may (thuong 1252 hoac 1258).
        return raw.decode("cp1252", "replace")


def _sniff(line: str) -> str:
    """Dau phan cach cua file: cai nao xuat hien nhieu nhat trong dong dau."""
    best, best_count = ",", 0
    for d in _DELIMS:
        n = line.count(d)
        if n > best_count:
            best, best_count = d, n
    return best


def _rows(text: str) -> List[List[str]]:
    """Tach van ban thanh o, bo dong trong va dong ghi chu."""
    lines = [ln for ln in text.splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []
    reader = csv.reader(lines, delimiter=_sniff(lines[0]))
    return [row for row in reader if any(c.strip() for c in row)]


def _email(cell: str) -> str:
    m = _EMAIL.search(cell or "")
    return m.group(0).strip(".") if m else ""


def _cell(row: Sequence[str], index: Optional[int]) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    return (row[index] or "").strip()


def _header(row: Sequence[str]) -> Dict[str, int]:
    """Nhan dien cot theo ten. Tra ve {} neu dong nay khong phai header."""
    folded = [fold(c) for c in row]
    idx: Dict[str, int] = {}
    for key, names in (("address", ADDRESS_COLUMNS), ("name", NAME_COLUMNS),
                       ("kind", TYPE_COLUMNS), ("archive", ARCHIVE_COLUMNS)):
        best: Optional[Tuple[int, int]] = None
        for i, cell in enumerate(folded):
            if cell in names:
                rank = names.index(cell)
                if best is None or rank < best[0]:
                    best = (rank, i)
        if best is not None:
            idx[key] = best[1]
    return idx if "address" in idx else {}


def _address_column(rows: Sequence[Sequence[str]]) -> int:
    """Cot nao chua dia chi email, khi ten cot khong nhan ra duoc."""
    counts: Dict[int, int] = {}
    for row in rows:
        for i, cell in enumerate(row):
            if _email(cell):
                counts[i] = counts.get(i, 0) + 1
    if not counts:
        return -1
    return min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]


def _has_archive(value: str) -> bool:
    """ArchiveStatus = Active, hoac ArchiveGuid khac GUID toan so 0."""
    v = fold(value)
    if not v:
        return False
    return v not in ("none", "0", "false", "no", "disabled",
                     "0" * 32)          # GUID rong: 00000000-0000-...-000000000000


HOWTO = (
    "Khong tim thay dia chi email nao trong file. Lay danh sach bang lenh nay "
    "trong Exchange Online PowerShell roi chay lai:\n"
    "  Get-Mailbox -ResultSize Unlimited | Select-Object "
    "PrimarySmtpAddress,DisplayName,RecipientTypeDetails,ArchiveStatus | "
    "Export-Csv -NoTypeInformation -Encoding UTF8 mailboxes.csv"
)


def parse(text: str, keep_all_types: bool = False,
          domains: Sequence[str] = ()) -> Parsed:
    """Van ban -> danh sach mailbox, kem nhung gi da bo va vi sao."""
    out = Parsed()
    rows = _rows(text)
    if not rows:
        raise MailboxListError("file khong co dong du lieu nao")

    idx = _header(rows[0])
    if idx:
        data = rows[1:]
        out.address_column = (rows[0][idx["address"]] or "").strip()
        if not data:
            raise MailboxListError(
                "file chi co dong tieu de, khong co mailbox nao")
    else:
        # Khong nhan ra ten cot: co the la danh sach dia chi tho khong header,
        # hoac header dat ten la. Tim cot nao chua dia chi va noi ro da doan gi.
        data = rows
        col = _address_column(rows)
        if col < 0:
            raise MailboxListError(HOWTO)
        idx = {"address": col}
        if len(rows[0]) > 1:
            out.warnings.append(
                "Khong nhan ra ten cot nao trong file nay, nen doc cot thu %d "
                "vi cot do chua dia chi email. Neu doc sai cot, doi ten cot "
                "chua dia chi thanh PrimarySmtpAddress roi chay lai." % (col + 1))

    wanted = {d.strip().lstrip("@").lower() for d in domains if d.strip()}
    seen: Dict[str, int] = {}
    for n, row in enumerate(data, start=1):
        addr = _email(_cell(row, idx["address"]))
        if not addr:
            # Dong khong co dia chi: header khong nhan ra, dong tong ket
            # ("...and 3 more"), hoac mailbox that su thieu PrimarySmtpAddress.
            desc = " | ".join(c.strip() for c in row if c.strip())
            out.skipped.append((desc[:60] or "(dong rong)",
                                "khong tim thay dia chi email trong dong nay"))
            continue

        kind = _cell(row, idx.get("kind"))
        if not keep_all_types:
            reason = SKIP_TYPES.get(fold(kind))
            if reason:
                out.skipped.append((addr, reason))
                continue

        domain = addr.rsplit("@", 1)[1].lower()
        if wanted and domain not in wanted:
            out.skipped.append((addr, "khong thuoc domain da chon"))
            continue

        key = addr.lower()
        if key in seen:
            out.skipped.append(
                (addr, "trung voi dong %d, chi lay mot lan" % seen[key]))
            continue
        seen[key] = n

        out.mailboxes.append(Mailbox(
            address=addr,
            name=_cell(row, idx.get("name")),
            kind=kind,
            archive=_has_archive(_cell(row, idx.get("archive"))),
            row=n,
        ))

    out.rows_read = len(data)
    out.warnings.extend(_review(out, idx))
    return out


def _review(out: Parsed, idx: Dict[str, int]) -> List[str]:
    """Nhung gi doc duoc tu file ma nguoi chay can biet TRUOC khi sync."""
    notes: List[str] = []
    if not out.mailboxes:
        return notes

    if "kind" not in idx:
        notes.append(
            "File khong co cot RecipientTypeDetails nen khong loc duoc phong "
            "hop va hop thu he thong. Them cot do vao lenh Get-Mailbox neu "
            "danh sach nay lay ca tenant.")

    if "archive" not in idx:
        notes.append(
            "File khong co cot ArchiveStatus nen khong biet mailbox nao co "
            "Online Archive. Archive la mailbox rieng, KHONG di qua IMAP: "
            "them cot do de biet truoc phai bao gi cho khach hang.")
    elif out.archived:
        sample = ", ".join(m.address for m in out.archived[:5])
        more = "" if len(out.archived) <= 5 else " va %d cai nua" % (len(out.archived) - 5)
        notes.append(
            "%d mailbox co Online Archive (%s%s). Archive la mailbox rieng, "
            "khong co duong IMAP nen tool KHONG chuyen duoc phan do -- phai "
            "keo ve hop thu chinh truoc khi sync, hoac xuat rieng."
            % (len(out.archived), sample, more))

    stub = [m.address for m in out.mailboxes
            if m.address.lower().endswith(".onmicrosoft.com")]
    if stub:
        notes.append(
            "%d dia chi con o dang @*.onmicrosoft.com (%s...). Thuong la "
            "mailbox chua gan domain that hoac chua co license -- kiem lai "
            "truoc khi tao mailbox ben dich."
            % (len(stub), stub[0]))
    return notes


# --------------------------------------------------------------------------- #
# Mat khau ben dich
# --------------------------------------------------------------------------- #

# Bo cac ky tu de doc lan (0/O, 1/l/I): con nguoi phai go lai chung vao giao
# dien tao mailbox ben dich.
_PW_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_PW_LOWER = "abcdefghijkmnopqrstuvwxyz"
_PW_DIGIT = "23456789"
# Khong dung dau phay, dau nhay, dau cach: users.csv la CSV va con nguoi con
# phai copy chuoi nay. Cac ky tu con lai vo hai vi imapsync doc mat khau tu
# file chu khong tu dong lenh.
_PW_MARK = "!#$%*+-=?@_"
_PW_POOLS = (_PW_UPPER, _PW_LOWER, _PW_DIGIT, _PW_MARK)


def gen_password(length: int = 16) -> str:
    """Mat khau ngau nhien cho mailbox dich, du bon nhom ky tu."""
    length = max(len(_PW_POOLS), length)
    chars = [secrets.choice(p) for p in _PW_POOLS]
    everything = "".join(_PW_POOLS)
    chars += [secrets.choice(everything) for _ in range(length - len(chars))]
    # Xao tron: neu khong, ky tu dau luon la chu hoa va ky tu thu tu luon la
    # dau -- ai doc file cung doan ra cong thuc.
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def dest_address(src: str, domain: str = "") -> str:
    """Dia chi ben dich. Mac dinh giu nguyen: phan lon ca migrate la doi nha
    cung cap chu khong doi domain."""
    domain = domain.strip().lstrip("@")
    if not domain:
        return src
    return "%s@%s" % (src.rsplit("@", 1)[0], domain.lower())


def build_rows(mailboxes: Sequence[Mailbox], dst_domain: str = "",
               dst_password: str = "", blank_passwords: bool = False,
               src_password: str = "") -> List[List[str]]:
    """Danh sach mailbox -> cac dong cua users.csv."""
    rows: List[List[str]] = []
    for m in mailboxes:
        if blank_passwords:
            password = ""
        elif dst_password:
            password = dst_password
        else:
            password = gen_password()
        rows.append([m.address, src_password,
                     dest_address(m.address, dst_domain), password])
    return rows


def write_users(path: Path, rows: Sequence[Sequence[str]],
                notes: Sequence[str] = ()) -> Path:
    """Ghi users.csv. Dong '#' o dau file duoc load_users() bo qua."""
    path = Path(path)
    with path.open("w", encoding="utf-8", newline="") as fh:
        for line in notes:
            fh.write("# %s\n" % line if line else "#\n")
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow(list(row))
    if os.name == "posix":
        # File nay chua mat khau ke tu day.
        os.chmod(path, 0o600)
    return path
