# -*- coding: utf-8 -*-
"""Ket xuat ket qua chay: bang tren man hinh, CSV, va HTML de gui bao cao.

Moi ham o day lam viec tren "row" (dict phang) chu khong phai object Result.
Nho vay lenh `report` doc lai duoc ket qua cua lan chay truoc tu file JSON
ma khong can dung lai Result.
"""

from __future__ import annotations

import csv
import html
import json
import textwrap
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .hints import diagnose

Row = Dict[str, str]

FIELDS = ["src_user", "dst_user", "ket_qua", "folder", "mail_chuyen", "mail_bo_qua",
          "bytes", "dung_luong", "loi", "thoi_gian", "duration_sec", "exit",
          "ghi_chu", "goi_y", "log", "mode"]


def human_bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < step:
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= step
    return "%.1f TB" % n


def human_duration(seconds) -> str:
    try:
        seconds = int(round(float(seconds or 0)))
    except (TypeError, ValueError):
        return "-"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dh%02dm" % (h, m)
    if m:
        return "%dm%02ds" % (m, s)
    return "%ds" % s


def _wrap(text: str, width: int = 78, indent: int = 0) -> str:
    """Xuong dong cho de doc tren terminal, cac dong sau thut vao."""
    lines = textwrap.wrap(text, max(20, width - indent)) or [text]
    return ("\n" + " " * indent).join(lines)


def _int(row: Row, key: str) -> int:
    try:
        return int(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def rows_from_results(results: Sequence) -> List[Row]:
    out = []
    for r in results:
        out.append({
            "src_user": r.user.src_user,
            "dst_user": r.user.dst_user,
            "ket_qua": "OK" if r.ok else "LOI",
            "folder": r.folders_synced or "-",
            "mail_chuyen": str(r.get("messages_transferred")),
            "mail_bo_qua": str(r.get("messages_skipped")),
            "bytes": str(r.get("bytes_transferred")),
            "dung_luong": human_bytes(r.get("bytes_transferred")),
            "loi": str(r.get("errors")),
            "thoi_gian": human_duration(r.duration),
            "duration_sec": "%.1f" % r.duration,
            "exit": r.exit_label or ("0" if r.ok else str(r.exit_code)),
            "ghi_chu": r.error,
            "log": str(r.logfile) if r.logfile else "",
            "mode": r.mode,
            "goi_y": " | ".join(r.hints),
        })
    return out


_COLUMNS = [
    ("src_user", "Nguon", 28),
    ("dst_user", "Dich", 28),
    ("ket_qua", "KQ", 4),
    ("folder", "Folder", 7),
    ("mail_chuyen", "Mail", 7),
    ("dung_luong", "Dung luong", 10),
    ("thoi_gian", "T.gian", 7),
    ("_note", "Ghi chu", 36),
]


def _note(row: Row) -> str:
    """Ghi chu chi co y nghia khi that bai; dong OK de trong cho de doc."""
    if row.get("ket_qua") == "OK":
        return ""
    return str(row.get("ghi_chu") or row.get("exit") or "")


def print_table(rows: Sequence[Row], emit=print) -> None:
    """`emit` de goi y dinh huong output (vd sang giao dien web)."""
    header = "  ".join(t.ljust(w) for _k, t, w in _COLUMNS)
    emit(header)
    emit("-" * len(header))
    for row in rows:
        cells = []
        for key, _title, width in _COLUMNS:
            val = _note(row) if key == "_note" else str(row.get(key, ""))
            if len(val) > width:
                val = val[: width - 1] + "~"
            cells.append(val.ljust(width))
        emit("  ".join(cells).rstrip())


def print_summary(rows: Sequence[Row], emit=print) -> None:
    ok = [r for r in rows if r.get("ket_qua") == "OK"]
    bad = [r for r in rows if r.get("ket_qua") != "OK"]
    total_msgs = sum(_int(r, "mail_chuyen") for r in rows)
    total_bytes = sum(_int(r, "bytes") for r in rows)
    total_errors = sum(_int(r, "loi") for r in rows)
    emit("")
    emit("Tong ket: %d/%d mailbox OK | %s mail | %s | %d loi le"
          % (len(ok), len(rows), "{:,}".format(total_msgs).replace(",", "."),
             human_bytes(total_bytes), total_errors))
    if bad:
        emit("")
        emit("Mailbox that bai:")
        for r in bad:
            emit("  - %s: %s" % (r.get("src_user"),
                                  r.get("ghi_chu") or r.get("exit") or "khong ro"))
            for tip in (r.get("goi_y") or "").split(" | "):
                if tip:
                    emit("      -> %s" % _wrap(tip, indent=9))
            if r.get("log"):
                emit("      log: %s" % r["log"])


def write_csv(rows: Sequence[Row], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig de Excel tren Windows mo khong bi loi font
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def save_run(rows: Sequence[Row], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "results": list(rows)}
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def load_run(path: Path) -> List[Row]:
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh).get("results", [])


# --------------------------------------------------------------------------- #
# Goi y: tinh lai tu log, khong doc tu file da luu
# --------------------------------------------------------------------------- #
# Truoc day goi y bi dong bang vao state/runs/*.json ngay luc chay. Khi luat
# chan doan tot len, moi bao cao cu van hien nguyen cai sai -- va bao cao cua
# mot mailbox se khong bao gio duoc sua neu no khong con duoc chay lai nua.
# Do la loi luu KET LUAN thay vi luu BANG CHUNG.
#
# Log moi la bang chung, va log van nam nguyen trong logs/. Nen doc lai log.
# Ba dieu phai luu y:
#   - Log co the rat lon (mot lan chay 12 tieng), nen chi doc phan duoi. Khoi
#     loi cua imapsync ("++++ Listing N errors") nam o cuoi; con nhung lan
#     hong som (sai mat khau, thieu module) thi ca file von da ngan.
#   - Dashboard hoi lai moi 1,2 giay luc dang chay, nen phai nho ket qua theo
#     (kich thuoc, mtime) de khong doc di doc lai mot file khong doi.
#   - Mat log thi quay ve dung goi y da luu, khong de trong.

_TAIL_BYTES = 256 * 1024
_hint_cache: Dict[str, tuple] = {}


def log_tail(path, limit: int = _TAIL_BYTES) -> str:
    """Doc phan duoi cua file, bo dong dau tien neu no bi cat giua chung."""
    p = Path(path)
    start = max(0, p.stat().st_size - limit)
    with p.open("rb") as fh:
        if start:
            fh.seek(start)
        raw = fh.read()
    text = raw.decode("utf-8", errors="replace")
    if start:
        _, _, text = text.partition("\n")
    return text


def hints_from_log(logpath: str) -> Optional[List[str]]:
    """Goi y tinh lai tu log. None neu khong con doc duoc log."""
    if not logpath:
        return None
    p = Path(logpath)
    try:
        st = p.stat()
    except OSError:
        return None
    key, stamp = str(p), (st.st_size, st.st_mtime)
    cached = _hint_cache.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        tips = diagnose(log_tail(p))
    except OSError:
        return None
    if len(_hint_cache) > 200:            # chay lau ngay thi dung phinh mai
        _hint_cache.clear()
    _hint_cache[key] = (stamp, tips)
    return tips


def hints_for_row(row: Row) -> List[str]:
    """Goi y cua mot dong bao cao, uu tien tinh lai tu log.

    Dong OK giu nguyen nhu da luu: goi y chi co nghia khi that bai, va viec
    doc lai log cua ca tram lan chay thanh cong la phi cong.
    """
    stored = [t for t in (row.get("goi_y") or "").split(" | ") if t]
    if row.get("ket_qua") != "LOI":
        return stored
    tips = hints_from_log(row.get("log", ""))
    return stored if tips is None else tips


def refresh_hints(rows: Sequence[Row]) -> List[Row]:
    """Ban sao cua rows voi truong goi_y da duoc tinh lai tu log."""
    return [dict(r, goi_y=" | ".join(hints_for_row(r))) for r in rows]


_HTML_HEAD = """<meta charset="utf-8">
<title>Bao cao migrate mail</title>
<style>
 body{font:14px/1.55 system-ui,"Segoe UI",Arial,sans-serif;margin:2rem;color:#16191d}
 h1{font-size:1.25rem;margin:0 0 .2rem}
 .sub{color:#6b7280;margin-bottom:1.5rem;font-size:13px}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{border:1px solid #e3e6ea;padding:.4rem .6rem;text-align:left}
 th{background:#f6f7f9;font-weight:600}
 tr.bad td{background:#fff5f5}
 .ok{color:#137333;font-weight:600}.err{color:#c5221f;font-weight:600}
 td.num{text-align:right;font-variant-numeric:tabular-nums}
 .tip{margin-top:.35rem;padding:.35rem .5rem;background:#fffbe6;border-left:3px solid #f0c000;font-size:12px}
 .totals{margin-top:1rem;padding:.7rem 1rem;background:#f6f7f9;border-radius:6px}
</style>
"""


def write_html(rows: Sequence[Row], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    trs = []
    for r in rows:
        good = r.get("ket_qua") == "OK"
        status = '<span class="ok">OK</span>' if good else '<span class="err">LOI</span>'
        # Escape truoc roi moi ghep the HTML: noi dung nay den tu log imapsync,
        # tuc la tu du lieu ngoai, khong duoc tin.
        note = html.escape(_note(r))
        tips = [t for t in (r.get("goi_y") or "").split(" | ") if t]
        note += "".join('<div class="tip">%s</div>' % html.escape(t) for t in tips)
        trs.append(
            "<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td class=num>%s</td><td class=num>%s</td><td class=num>%s</td>"
            "<td class=num>%s</td><td>%s</td></tr>" % (
                "" if good else ' class="bad"',
                html.escape(str(r.get("src_user", ""))),
                html.escape(str(r.get("dst_user", ""))), status,
                html.escape(str(r.get("folder", ""))),
                html.escape(str(r.get("mail_chuyen", ""))),
                html.escape(str(r.get("dung_luong", ""))),
                html.escape(str(r.get("thoi_gian", ""))),
                html.escape(str(r.get("loi", ""))), note))
    ok = sum(1 for r in rows if r.get("ket_qua") == "OK")
    total_msgs = sum(_int(r, "mail_chuyen") for r in rows)
    total_bytes = sum(_int(r, "bytes") for r in rows)
    body = (
        "<h1>Bao cao migrate mail: Google &rarr; IceWarp</h1>"
        '<div class="sub">Tao luc %s</div>'
        "<table><thead><tr><th>Nguon</th><th>Dich</th><th>Ket qua</th><th>Folder</th>"
        "<th>Mail</th><th>Dung luong</th><th>Thoi gian</th><th>Loi le</th>"
        "<th>Ghi chu</th></tr></thead><tbody>%s</tbody></table>"
        '<div class="totals">%d/%d mailbox thanh cong &middot; %s mail &middot; %s</div>'
        % (time.strftime("%Y-%m-%d %H:%M:%S"), "".join(trs), ok, len(rows),
           "{:,}".format(total_msgs), human_bytes(total_bytes)))
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(_HTML_HEAD + body + "\n")
    return path
