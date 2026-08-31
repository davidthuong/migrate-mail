"""Doc users.csv -> danh sach mailbox can migrate."""

from __future__ import annotations

import csv
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

COLUMNS = ["src_user", "src_password", "dst_user", "dst_password"]
# Cot luon phai co. src_password chi bat buoc khi nguon dang nhap bang mat
# khau; voi Microsoft 365 chay OAuth2 thi khong ai co mat khau cua user ca.
REQUIRED = ["src_user", "dst_user", "dst_password"]


@dataclass
class User:
    src_user: str
    src_password: str
    dst_user: str
    dst_password: str
    row: int

    @property
    def slug(self) -> str:
        """Ten an toan de dat file log/state."""
        return re.sub(r"[^A-Za-z0-9._@-]", "_", self.src_user)

    def __repr__(self) -> str:  # tranh lo password khi debug
        return "User(%s -> %s)" % (self.src_user, self.dst_user)


def _clean_app_password(value: str) -> str:
    """Google hien app password dang 'abcd efgh ijkl mnop'; IMAP nhan ban lien nhau."""
    return value.replace(" ", "").replace("\u00a0", "").strip()


def check_permissions(path: Path) -> str:
    """Canh bao neu file chua password doc duoc boi user khac (chi co nghia tren POSIX)."""
    if os.name != "posix":
        return ""
    mode = os.stat(path).st_mode
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        return "CANH BAO: %s dang doc duoc boi group/other. Chay: chmod 600 %s" % (path, path)
    return ""


def load_users(path: Path, need_src_password: bool = True) -> List[User]:
    """Doc users.csv.

    `need_src_password` = False khi nguon dang nhap khong bang mat khau
    (Microsoft 365 chay OAuth2): khi do cot src_password co the de trong hoac
    khong co trong file.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            "khong thay %s -- copy users.example.csv thanh users.csv roi dien vao" % path
        )
    warn = check_permissions(path)
    if warn:
        print(warn, file=sys.stderr)

    required = list(REQUIRED)
    if need_src_password:
        required.insert(1, "src_password")

    users: List[User] = []
    seen_src, seen_dst = set(), set()
    with path.open(newline="", encoding="utf-8-sig") as fh:
        # Bo dong trong va dong bat dau bang '#' truoc khi dua vao csv reader.
        lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
        reader = csv.DictReader(lines)
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                "users.csv thieu cot: %s (can du: %s)" % (", ".join(missing), ", ".join(required))
            )
        for i, rec in enumerate(reader, start=2):
            vals = {k: (rec.get(k) or "").strip() for k in COLUMNS}
            if not any(vals.values()):
                continue
            empty = [k for k in required if not vals[k]]
            if empty:
                raise ValueError("users.csv dong %d thieu gia tri: %s" % (i, ", ".join(empty)))

            u = User(
                src_user=vals["src_user"],
                src_password=_clean_app_password(vals["src_password"]),
                dst_user=vals["dst_user"],
                dst_password=vals["dst_password"],
                row=i,
            )
            if u.src_user.lower() in seen_src:
                raise ValueError("users.csv dong %d: src_user %s bi trung" % (i, u.src_user))
            if u.dst_user.lower() in seen_dst:
                raise ValueError("users.csv dong %d: dst_user %s bi trung" % (i, u.dst_user))
            seen_src.add(u.src_user.lower())
            seen_dst.add(u.dst_user.lower())

            if len(u.src_password) == 16 and " " in vals["src_password"]:
                pass  # app password co khoang trang -> da normalize, khong sao
            users.append(u)

    if not users:
        raise ValueError("users.csv khong co dong du lieu nao")
    return users


def filter_users(users: List[User], only: List[str]) -> List[User]:
    """Loc theo --only a@x.com,b@x.com (khop src_user hoac dst_user)."""
    if not only:
        return users
    wanted = {s.strip().lower() for s in only if s.strip()}
    out = [u for u in users if u.src_user.lower() in wanted or u.dst_user.lower() in wanted]
    found = {u.src_user.lower() for u in out} | {u.dst_user.lower() for u in out}
    unknown = wanted - found
    if unknown:
        raise ValueError("--only co dia chi khong ton tai trong users.csv: %s" % ", ".join(sorted(unknown)))
    return out
