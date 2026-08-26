# -*- coding: utf-8 -*-
"""Doi chieu ngay thang cua mail giua Gmail va IceWarp sau khi sync.

Vi sao can buoc nay: IMAP co hai loai ngay.

  INTERNALDATE  ngay server gan cho mail luc no duoc dua vao hop thu.
                Day la thu hau het mail client dung de sap xep va hien thi.
  Date:         header nam trong than mail, khong bao gio doi.

imapsync GUI ngay INTERNALDATE cua nguon sang cho dich qua lenh APPEND. Nhung
server dich co ton trong ngay do hay khong lai la chuyen khac -- neu no bo qua,
toan bo mail se mang ngay cua luc chuyen. Do chinh la trieu chung "mail nhay het
ve ngay migrate". Module nay doc INTERNALDATE that o ca hai dau roi so, de biet
chac chan thay vi doan.
"""

from __future__ import annotations

import imaplib
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Sai lech duoi nguong nay coi nhu khop. INTERNALDATE chi chinh xac toi giay,
# va cach viet mui gio hai ben co the khac nhau du cung mot thoi diem.
TOLERANCE_SECONDS = 2

_MSGID_RE = re.compile(rb"message-id\s*:\s*(<[^>]*>)", re.I)
_EXISTS_RE = re.compile(rb"(\d+)")


@dataclass
class FolderCheck:
    source_folder: str          # ten hien thi cua folder nguon
    dest_folder: str
    compared: int = 0           # so mail doi chieu duoc o ca hai dau
    matched: int = 0
    mismatched: int = 0
    missing_on_dest: int = 0
    source_total: int = 0
    dest_total: int = 0
    error: str = ""
    samples: List[Tuple[str, float, float]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error and self.mismatched == 0


@dataclass
class UserCheck:
    src_user: str
    dst_user: str
    folders: List[FolderCheck] = field(default_factory=list)
    error: str = ""

    @property
    def compared(self) -> int:
        return sum(f.compared for f in self.folders)

    @property
    def mismatched(self) -> int:
        return sum(f.mismatched for f in self.folders)

    @property
    def missing(self) -> int:
        return sum(f.missing_on_dest for f in self.folders)

    @property
    def ok(self) -> bool:
        return not self.error and all(f.ok for f in self.folders)


def quote_folder(name: str) -> str:
    """Ten folder Gmail co dau cach va ngoac vuong, bat buoc phai boc nhay."""
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % escaped


def parse_internaldate(raw: bytes) -> Optional[float]:
    """Doi INTERNALDATE trong response IMAP thanh epoch. None neu khong doc duoc.

    Dung imaplib.Internaldate2tuple vi no xu ly san mui gio (+0700, -0500...),
    nen hai dau ghi mui gio khac nhau van ra cung mot thoi diem.
    """
    try:
        parsed = imaplib.Internaldate2tuple(raw)
    except Exception:
        return None
    if not parsed:
        return None
    try:
        return time.mktime(parsed)
    except (OverflowError, ValueError):
        return None


def parse_message_id(raw: bytes) -> str:
    m = _MSGID_RE.search(raw or b"")
    return m.group(1).decode("ascii", "replace").strip() if m else ""


def parse_fetch_response(data) -> Dict[str, float]:
    """Doc ket qua FETCH thanh map: Message-Id -> epoch cua INTERNALDATE."""
    out: Dict[str, float] = {}
    for item in data or []:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        head, body = item[0], item[1]
        epoch = parse_internaldate(head)
        msgid = parse_message_id(body)
        if msgid and epoch is not None:
            out[msgid] = epoch
    return out


def sample_sequence_set(total: int, cap: int) -> str:
    """Chon toi da `cap` mail rai deu tu 1..total, tra ve chuoi sequence-set."""
    if total <= 0:
        return ""
    if cap <= 0 or total <= cap:
        return "1:%d" % total
    step = total / float(cap)
    seqs = sorted({int(i * step) + 1 for i in range(cap)})
    seqs = [s for s in seqs if 1 <= s <= total]
    return ",".join(str(s) for s in seqs)


def folder_message_count(select_response) -> int:
    if not select_response:
        return 0
    first = select_response[0]
    if isinstance(first, bytes):
        m = _EXISTS_RE.search(first)
        if m:
            return int(m.group(1))
    return 0


def fetch_index(conn, folder_raw: str, cap: int) -> Tuple[Dict[str, float], int]:
    """Lay map Message-Id -> epoch cho mot folder. Tra ve (map, tong so mail)."""
    typ, data = conn.select(quote_folder(folder_raw), readonly=True)
    if typ != "OK":
        raise RuntimeError("khong mo duoc folder")
    total = folder_message_count(data)
    if total == 0:
        return {}, 0
    seq = sample_sequence_set(total, cap)
    typ, fetched = conn.fetch(seq, "(INTERNALDATE BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
    if typ != "OK":
        raise RuntimeError("FETCH that bai")
    return parse_fetch_response(fetched), total


def compare_indexes(src: Dict[str, float], dst: Dict[str, float],
                    tolerance: int = TOLERANCE_SECONDS,
                    max_samples: int = 3) -> Tuple[int, int, int, List]:
    """So hai map ngay. Tra ve (doi chieu duoc, khop, lech, vi du lech)."""
    compared = matched = mismatched = 0
    samples: List[Tuple[str, float, float]] = []
    for msgid, src_epoch in src.items():
        dst_epoch = dst.get(msgid)
        if dst_epoch is None:
            continue
        compared += 1
        if abs(src_epoch - dst_epoch) <= tolerance:
            matched += 1
        else:
            mismatched += 1
            if len(samples) < max_samples:
                samples.append((msgid, src_epoch, dst_epoch))
    return compared, matched, mismatched, samples
