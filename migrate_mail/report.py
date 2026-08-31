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
          "ghi_chu", "goi_y", "log", "mode",
          # Provider cua lan chay do. Can luu lai vi goi y duoc TINH LAI tu log
          # moi lan xem bao cao: khong co hai truong nay thi khong biet log kia
          # la cua Gmail hay cua Exchange, va se dua ra goi y cua nha cung cap
          # khac. Dong cu (truoc khi co da provider) khong co -> de trong.
          "src_provider", "dst_provider"]


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


def rows_from_results(results: Sequence, cfg=None) -> List[Row]:
    src_provider = cfg.source.provider.key if cfg else ""
    dst_provider = cfg.dest.provider.key if cfg else ""
    out = []
    for r in results:
        out.append({
            "src_provider": src_provider,
            "dst_provider": dst_provider,
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
    # Dau thoi gian chi chi tiet den giay. Hai lan chay ket thuc trong cung
    # mot giay se de len nhau va lam mat han mot lan chay khoi bao cao gop.
    # Hau to dung '_' chu khong dung '-' hay '.': latest_rows sap xep theo ten
    # file de biet lan nao moi hon, ma '_' (0x5F) lon hon '.' (0x2E) nen
    # "...-000000_2.json" xep SAU "...-000000.json", dung thu tu thoi gian.
    n = 2
    while path.exists():
        path = path.parent / ("%s_%d%s" % (path.stem.split("_")[0], n, path.suffix))
        n += 1
    payload = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "results": list(rows)}
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def load_run(path: Path) -> List[Row]:
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh).get("results", [])


def latest_rows(runs_dir) -> Dict[str, Row]:
    """Ket qua gan nhat cua TUNG mailbox, gop tu moi lan chay da luu.

    Mot file run chi chua nhung mailbox cua lan chay do. Sau vai dem chay rai
    rac -- 8 hop mot dem, roi tung hop le chay lai -- khong file nao con chua
    du danh sach. Muon nhin toan canh thi phai gop, lay dong moi nhat cua tung
    dia chi.

    Ham nay o day chu khong o web.py vi ca dashboard lan lenh `report` deu can:
    truoc day chi dashboard co, nen hai ben bao cao ra hai ket qua khac nhau
    tren cung mot du lieu.
    """
    runs_dir = Path(runs_dir)
    out: Dict[str, Row] = {}
    if not runs_dir.exists():
        return out
    for path in sorted(runs_dir.glob("*.json")):     # cu -> moi, ban sau de len
        try:
            for row in load_run(path):
                if row.get("mode") in ("sync", "dry"):
                    out[row.get("src_user", "")] = dict(row, run=path.stem)
        except (OSError, ValueError):
            continue
    return out


def _float(row: Row, key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def merged_rows(runs_dir) -> List[Row]:
    """Mot dong cho moi mailbox, gop tu tat ca cac lan chay.

    Trang thai (ket qua, folder, ghi chu, log) lay tu lan chay MOI NHAT -- do
    la tinh hinh hien tai. Nhung khoi luong (mail, dung luong, thoi gian) thi
    CONG DON qua moi lan chay sync.

    Vi sao phai cong don: mot hop thu bi nguon cat giua chung roi chay lai da
    chuyen mail o ca hai lan, nhung moi dong chi mang thong ke cua rieng lan
    do ("Messages transferred" cua imapsync). Lay lan cuoi lam bao cao la ke
    thieu cong cua chinh minh -- co lan bao 87.936 mail trong khi thuc te da
    chuyen gan 122.700.

    Cong don khong so dem trung: imapsync bo qua mail da co ben dich, nen lan
    chay sau chi dem phan no that su chep them.

    Lan chay --dry khong chep gi ca nen khong duoc cong vao. So loi thi lay
    tu lan chay cuoi chu khong cong: cung mot mail hong se bi dem lai o moi
    lan chay.
    """
    runs_dir = Path(runs_dir)
    latest = latest_rows(runs_dir)
    if not latest:
        return []

    totals: Dict[str, Dict[str, float]] = {}
    for path in sorted(runs_dir.glob("*.json")):
        try:
            rows = load_run(path)
        except (OSError, ValueError):
            continue
        for r in rows:
            if r.get("mode") != "sync":
                continue
            t = totals.setdefault(r.get("src_user", ""),
                                  {"mail": 0.0, "bytes": 0.0, "sec": 0.0})
            t["mail"] += _int(r, "mail_chuyen")
            t["bytes"] += _int(r, "bytes")
            t["sec"] += _float(r, "duration_sec")

    out: List[Row] = []
    for user, row in latest.items():
        t = totals.get(user)
        if not t:                       # chi tung chay --dry
            out.append(dict(row))
            continue
        out.append(dict(row,
                        mail_chuyen=str(int(t["mail"])),
                        bytes=str(int(t["bytes"])),
                        dung_luong=human_bytes(t["bytes"]),
                        duration_sec="%.1f" % t["sec"],
                        thoi_gian=human_duration(t["sec"])))
    return sorted(out, key=lambda r: r.get("src_user", ""))


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


def hints_from_log(logpath: str, source: Optional[str] = None,
                   dest: Optional[str] = None) -> Optional[List[str]]:
    """Goi y tinh lai tu log. None neu khong con doc duoc log."""
    if not logpath:
        return None
    p = Path(logpath)
    try:
        st = p.stat()
    except OSError:
        return None
    key, stamp = (str(p), source, dest), (st.st_size, st.st_mtime)
    cached = _hint_cache.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        tips = diagnose(log_tail(p), source=source, dest=dest)
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
    tips = hints_from_log(row.get("log", ""),
                          row.get("src_provider") or None,
                          row.get("dst_provider") or None)
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


def _html_title(rows: Sequence[Row]) -> str:
    """": Gmail -> IceWarp" neu moi dong cung mot cap provider, khong thi rong.

    Bao cao gop (`report --all`) co the tron nhieu cuoc migrate khac nhau; khi
    do de tieu de trung tinh con hon ghi ten mot cap va noi sai ve phan con lai.
    """
    from . import providers
    pairs = {(r.get("src_provider") or "", r.get("dst_provider") or "")
             for r in rows}
    if len(pairs) != 1:
        return ""
    src, dst = pairs.pop()
    if not src or not dst:
        return ""
    try:
        return ": %s &rarr; %s" % (html.escape(providers.get(src).name),
                                   html.escape(providers.get(dst).name))
    except ValueError:
        return ""


def write_html(rows: Sequence[Row], path: Path, note_text: str = "") -> Path:
    """`note_text` giai thich cot nao mang nghia gi, in ngay duoi tieu de.

    Bao cao gop (`report --all`) cong don khoi luong qua nhieu lan chay, khac
    voi bao cao mot lan chay -- nguoi doc phai biet dieu do truoc khi tin so.
    """
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
        "<h1>Bao cao migrate mail%s</h1>" % _html_title(rows) +
        '<div class="sub">Tao luc %s%s</div>'
        "<table><thead><tr><th>Nguon</th><th>Dich</th><th>Ket qua</th><th>Folder</th>"
        "<th>Mail</th><th>Dung luong</th><th>Thoi gian</th><th>Loi le</th>"
        "<th>Ghi chu</th></tr></thead><tbody>%s</tbody></table>"
        '<div class="totals">%d/%d mailbox thanh cong &middot; %s mail &middot; %s</div>'
        % (time.strftime("%Y-%m-%d %H:%M:%S"),
           (" &middot; " + html.escape(note_text)) if note_text else "",
           "".join(trs), ok, len(rows),
           "{:,}".format(total_msgs), human_bytes(total_bytes)))
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(_HTML_HEAD + body + "\n")
    return path
