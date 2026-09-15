# -*- coding: utf-8 -*-
"""Bao cao ban giao: to giay dua cho khach khi ket thuc mot cuoc migrate.

Khac voi `report --out ...` o cho nao: bao cao kia la man hinh van hanh, doc
de biet dem qua chay toi dau. To nay la chung tu -- no phai tu noi duoc pham
vi lam gi, ket qua ra sao, KIEM CHUNG bang cach nao, cai gi KHONG nam trong
pham vi, va cho de hai ben ky.

Mot dieu khac cac module con lai: chuoi o day co dau tieng Viet. Ly do ky
thuat chu khong phai tham my -- ca file nay chi ghi ra HTML bang
`encoding="utf-8"`, khong bao gio in ra stdout. Terminal tren VPS khach hay
chay locale C, va `print("Bao cao")` co dau se nem UnicodeEncodeError o dung
luc nguoi ta can nhin ket qua nhat; day la ly do phan con lai cua tool viet
khong dau. Rang buoc do khong ap len mot file HTML. Va mot to giay co chu ky
ma viet khong dau thi khach doc duoc, nhung ho se nghi ve minh mot kieu khac.

=> Quy tac: KHONG in bat ky chuoi nao trong file nay ra terminal.
"""

from __future__ import annotations

import html
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .report import Row, human_bytes

# Nguong sai lech coi nhu khop, lay tu chinh module verify de hai noi khong
# the noi hai so khac nhau.
from .verify import TOLERANCE_SECONDS


def _int(row: Row, key: str) -> int:
    try:
        return int(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def vn_number(n) -> str:
    """12345 -> '12.345'. Tieng Viet ngan cach hang nghin bang dau cham."""
    try:
        return "{:,}".format(int(n)).replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def vn_date(stamp: str = "") -> str:
    """'20260825-101500' hoac '2026-08-25 10:15:00' -> '25/08/2026'."""
    digits = "".join(ch for ch in str(stamp) if ch.isdigit())
    if len(digits) >= 8:
        y, m, d = digits[0:4], digits[4:6], digits[6:8]
        if y.isdigit() and 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            return "%s/%s/%s" % (d, m, y)
    return ""


def period_from_runs(run_names: Sequence[str]) -> str:
    """Khoang thoi gian cua cuoc migrate, doc tu ten cac file run.

    Ten file dang '20260825-101500.json'. Lay cai dau va cai cuoi. Mot lan
    chay duy nhat thi tra ve mot ngay chu khong phai 'X - X'.
    """
    days = [d for d in (vn_date(n) for n in sorted(run_names)) if d]
    if not days:
        return ""
    if days[0] == days[-1]:
        return days[0]
    return "%s – %s" % (days[0], days[-1])


# --------------------------------------------------------------------------- #
# Nhung gi KHONG di qua duoc IMAP
# --------------------------------------------------------------------------- #
# Day la muc quan trong nhat cua to giay nay, va la muc duy nhat khach se doc
# ky sau khi da ky. Noi truoc o day thi no la pham vi; de khach tu phat hien
# sau ba ngay thi no la su co, va luc do khong con giay to nao ben minh ca.

OUT_OF_SCOPE = [
    "Lịch (Calendar) và lời mời họp",
    "Danh bạ (Contacts)",
    "Công việc (Tasks) và ghi chú (Notes)",
    "Bộ lọc, quy tắc tự động, chữ ký, và cấu hình chuyển tiếp thư",
    "Quyền chia sẻ hộp thư và nhóm phân phối",
]

OUT_OF_SCOPE_NOTE = (
    "Giao thức IMAP chỉ chở thư. Những hạng mục trên không đi qua được bằng "
    "công cụ này và cần xuất/nhập riêng nếu hai bên có thỏa thuận thêm."
)


_CSS = """
 @page { size: A4; margin: 18mm 16mm; }
 * { box-sizing: border-box; }
 body { font: 13px/1.6 "Segoe UI", system-ui, Arial, sans-serif;
        color: #16191d; margin: 0; background: #fff; }
 .sheet { max-width: 820px; margin: 0 auto; padding: 32px 28px 56px; }
 h1 { font-size: 24px; letter-spacing: .4px; margin: 0 0 6px; }
 h2 { font-size: 15px; margin: 32px 0 10px; padding-bottom: 6px;
      border-bottom: 2px solid #16191d; }
 h3 { font-size: 13px; margin: 18px 0 6px; }
 p { margin: 0 0 10px; }
 .cover { border-bottom: 3px solid #16191d; padding-bottom: 20px; }
 .kicker { font-size: 11px; letter-spacing: .16em; text-transform: uppercase;
           color: #6b7280; margin-bottom: 10px; }
 .meta { margin-top: 18px; border-collapse: collapse; width: 100%; }
 .meta th { width: 150px; text-align: left; font-weight: 600; color: #4b5563;
            padding: 5px 10px 5px 0; vertical-align: top; }
 .meta td { padding: 5px 0; vertical-align: top; }
 .fill { display: inline-block; min-width: 220px;
         border-bottom: 1px dotted #9aa3ad; }
 .cards { display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0 4px; }
 .card { flex: 1 1 150px; border: 1px solid #dfe3e8; padding: 10px 12px; }
 .card b { display: block; font-size: 20px; font-variant-numeric: tabular-nums; }
 .card span { font-size: 11px; color: #6b7280; }
 table.grid { border-collapse: collapse; width: 100%; font-size: 12px;
              margin-top: 8px; }
 table.grid th, table.grid td { border: 1px solid #dfe3e8; padding: 5px 8px;
                                text-align: left; vertical-align: top; }
 table.grid th { background: #f4f6f8; font-weight: 600; }
 table.grid td.num { text-align: right; font-variant-numeric: tabular-nums;
                     white-space: nowrap; }
 tr.bad td { background: #fdf3f2; }
 .ok { color: #15703c; font-weight: 600; }
 .err { color: #b4291f; font-weight: 600; }
 ul { margin: 6px 0 10px; padding-left: 20px; }
 li { margin-bottom: 3px; }
 .note { font-size: 12px; color: #4b5563; }
 .method { background: #f4f6f8; border-left: 3px solid #9aa3ad;
           padding: 10px 12px; font-size: 12px; margin: 10px 0; }
 .tip { font-size: 11px; color: #6b5200; background: #fffbe6;
        border-left: 3px solid #f0c000; padding: 4px 7px; margin-top: 4px; }
 .sign { display: flex; gap: 40px; margin-top: 18px; }
 .sign div { flex: 1; }
 .sign .line { margin-top: 68px; border-top: 1px solid #16191d;
               padding-top: 5px; font-size: 11px; color: #6b7280; }
 footer { margin-top: 36px; padding-top: 10px; border-top: 1px solid #dfe3e8;
          font-size: 11px; color: #6b7280; }
 @media print {
   .sheet { padding: 0; max-width: none; }
   h2 { page-break-after: avoid; }
   table.grid, .sign, .card { page-break-inside: avoid; }
 }
"""


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _fill(value: str) -> str:
    """Gia tri, hoac mot dong gach de dien tay khi chua khai bao."""
    return _esc(value) if value else '<span class="fill">&nbsp;</span>'


def _meta_rows(pairs) -> str:
    return "".join("<tr><th>%s</th><td>%s</td></tr>" % (_esc(k), v)
                   for k, v in pairs)


def _summary_cards(rows: Sequence[Row]) -> str:
    ok = sum(1 for r in rows if r.get("ket_qua") == "OK")
    mails = sum(_int(r, "mail_chuyen") for r in rows)
    size = sum(_int(r, "bytes") for r in rows)
    cards = [
        ("%d/%d" % (ok, len(rows)), "hộp thư hoàn tất"),
        (vn_number(mails), "thư đã chuyển"),
        (human_bytes(size), "dung lượng"),
    ]
    return '<div class="cards">%s</div>' % "".join(
        '<div class="card"><b>%s</b><span>%s</span></div>' % (_esc(v), _esc(t))
        for v, t in cards)


def _mailbox_table(rows: Sequence[Row]) -> str:
    trs = []
    for r in rows:
        good = r.get("ket_qua") == "OK"
        status = ('<span class="ok">Hoàn tất</span>' if good
                  else '<span class="err">Chưa đạt</span>')
        # Noi dung duoi day den tu log imapsync, tuc la du lieu ngoai: escape
        # truoc roi moi ghep the.
        note = "" if good else _esc(r.get("ghi_chu") or r.get("exit") or "")
        for tip in (r.get("goi_y") or "").split(" | "):
            if tip and not good:
                note += '<div class="tip">%s</div>' % _esc(tip)
        trs.append(
            "<tr%s><td>%s</td><td>%s</td><td>%s</td>"
            '<td class="num">%s</td><td class="num">%s</td>'
            '<td class="num">%s</td><td>%s</td></tr>' % (
                "" if good else ' class="bad"',
                _esc(r.get("src_user")), _esc(r.get("dst_user")), status,
                _esc(r.get("folder")), vn_number(r.get("mail_chuyen")),
                _esc(r.get("dung_luong")), note))
    return (
        '<table class="grid"><thead><tr>'
        "<th>Hộp thư nguồn</th><th>Hộp thư đích</th><th>Kết quả</th>"
        "<th>Thư mục</th><th>Thư</th><th>Dung lượng</th><th>Ghi chú</th>"
        "</tr></thead><tbody>%s</tbody></table>" % "".join(trs))


def _verify_section(verify_users: Dict[str, dict]) -> str:
    """Bang doi chieu ngay thang. Rong thi noi ro la chua chay, khong im lang.

    Im lang o day la kieu im lang toi nhat: nguoi doc se cho rang da kiem va
    khong co van de gi, trong khi that ra chua ai kiem ca.
    """
    if not verify_users:
        return (
            "<h2>Đối chiếu ngày tháng</h2>"
            '<p class="note">Chưa chạy bước đối chiếu, nên báo cáo này không '
            "kết luận gì về ngày tháng của thư sau khi chuyển. Chạy "
            "<code>postboat.py verify</code> rồi xuất lại báo cáo nếu cần hạng mục "
            "này trong biên bản.</p>")

    users = [verify_users[k] for k in sorted(verify_users)]
    cap = max([int(u.get("sample") or 0) for u in users] or [0])
    total_cmp = sum(int(u.get("compared") or 0) for u in users)
    total_bad = sum(int(u.get("mismatched") or 0) for u in users)
    total_missing = sum(int(u.get("missing") or 0) for u in users)
    total_no_id = sum(int(u.get("without_msgid") or 0) for u in users)

    trs = []
    for u in users:
        bad = int(u.get("mismatched") or 0)
        err = u.get("error") or ""
        if err:
            verdict = '<span class="err">Không kiểm được</span>'
        elif bad:
            verdict = '<span class="err">Lệch %s</span>' % vn_number(bad)
        else:
            verdict = '<span class="ok">Khớp</span>'
        trs.append(
            "<tr%s><td>%s</td>"
            '<td class="num">%s</td><td class="num">%s</td>'
            '<td class="num">%s</td><td>%s</td></tr>' % (
                "" if not (bad or err) else ' class="bad"',
                _esc(u.get("src_user")),
                vn_number(u.get("compared")), vn_number(bad),
                vn_number(u.get("missing")),
                verdict + ('<div class="tip">%s</div>' % _esc(err) if err else "")))

    method = (
        "Phương pháp: với mỗi thư mục, lấy mẫu %s thư trải đều ở hộp thư "
        "nguồn, tra cùng thư đó ở hộp thư đích theo Message-Id, rồi so ngày "
        "nhận thực tế (INTERNALDATE) của hai bên. Sai lệch dưới %d giây coi "
        "như khớp, vì hai máy chủ có thể ghi múi giờ khác nhau cho cùng một "
        "thời điểm."
        % (("tối đa %s" % vn_number(cap)) if cap else "một số", TOLERANCE_SECONDS))

    lines = [
        "<h2>Đối chiếu ngày tháng</h2>",
        '<div class="method">%s</div>' % method,
        '<table class="grid"><thead><tr><th>Hộp thư</th><th>Thư đối chiếu</th>'
        "<th>Lệch ngày</th><th>Không thấy ở đích</th><th>Kết luận</th>"
        "</tr></thead><tbody>%s</tbody></table>" % "".join(trs),
    ]

    if total_cmp:
        # Dau thap phan cua tieng Viet la dau phay, nhu dau ngan cach hang
        # nghin la dau cham. Mot to giay dua cho khach ma viet "0.07%" thi
        # nguoi doc ky se thay ngay no duoc may in ra chu khong ai doc lai.
        rate = ("%.2f" % (100.0 * total_bad / total_cmp)).replace(".", ",")
        lines.append(
            "<p>Tổng cộng đối chiếu %s thư, lệch ngày %s (%s%%).</p>"
            % (vn_number(total_cmp), vn_number(total_bad), rate))
    if total_missing:
        lines.append(
            '<p class="note">%s thư trong mẫu không tìm thấy ở đích. Con số này '
            "lấy trên mẫu, không phải đếm đầy đủ; số đếm đầy đủ nằm ở dòng "
            "<em>Messages found in host1 not in host2</em> trong nhật ký chuyển "
            "của từng hộp thư.</p>" % vn_number(total_missing))
    if total_no_id:
        lines.append(
            '<p class="note">%s thư ở nguồn không có Message-Id nên không ghép '
            "được cặp để so ngày — thường gặp ở thư nháp và thư do máy quét "
            "sinh ra. Những thư này vẫn được chuyển bình thường; chỉ riêng "
            "phép đối chiếu ngày là không với tới chúng.</p>" % vn_number(total_no_id))
    return "".join(lines)


def _signature_block(info) -> str:
    performer = getattr(info, "performer", "") or ""
    customer = getattr(info, "customer", "") or ""
    signer = getattr(info, "signer", "") or ""
    signer_title = getattr(info, "signer_title", "") or ""
    cust_signer = getattr(info, "customer_signer", "") or ""
    cust_title = getattr(info, "customer_title", "") or ""

    def col(side_label: str, org: str, who: str, title: str) -> str:
        head = "%s%s" % (_esc(side_label),
                         ("<br>%s" % _esc(org)) if org else "")
        foot = _esc(who) if who else "&nbsp;"
        if title:
            foot += "<br>%s" % _esc(title)
        return ('<div><h3>%s</h3><p class="note">Ký, ghi rõ họ tên</p>'
                '<div class="line">%s</div></div>' % (head, foot))

    return (
        "<h2>Xác nhận bàn giao</h2>"
        '<p class="note">Hai bên xác nhận khối lượng và kết quả nêu trong báo '
        "cáo này là đúng với thực tế đã thực hiện.</p>"
        '<div class="sign">%s%s</div>' % (
            col("BÊN THỰC HIỆN", performer, signer, signer_title),
            col("BÊN NHẬN BÀN GIAO", customer, cust_signer, cust_title)))


def build_html(rows: Sequence[Row], verify_users: Optional[Dict[str, dict]] = None,
               info=None, source_name: str = "", dest_name: str = "",
               period: str = "", now: Optional[str] = None) -> str:
    """Toan bo tai lieu ban giao duoi dang mot chuoi HTML.

    Tach khoi `write_handover` de test doc duoc ket qua ma khong can cham dia.
    """
    rows = list(rows)
    verify_users = verify_users or {}
    now = now or time.strftime("%d/%m/%Y %H:%M")

    customer = getattr(info, "customer", "") or ""
    scope = getattr(info, "scope", "") or ""
    contact = getattr(info, "contact", "") or ""

    if not scope:
        # Tu mo ta pham vi tu chinh du lieu, de o trong thi to giay mat nghia.
        route = ("%s sang %s" % (source_name, dest_name)
                 if source_name and dest_name else "")
        scope = "Chuyển thư của %d hộp thư%s." % (
            len(rows), (" từ %s" % route) if route else "")

    failed = [r for r in rows if r.get("ket_qua") != "OK"]

    parts = [
        '<div class="sheet">',
        '<div class="cover">',
        '<div class="kicker">Biên bản bàn giao</div>',
        "<h1>Báo cáo chuyển đổi hộp thư</h1>",
        '<table class="meta">',
        _meta_rows([
            ("Khách hàng", _fill(customer)),
            ("Bên thực hiện", _fill(getattr(info, "performer", "") or "")),
            ("Hệ thống nguồn", _fill(source_name)),
            ("Hệ thống đích", _fill(dest_name)),
            ("Thời gian thực hiện", _fill(period)),
            ("Ngày lập báo cáo", _esc(now)),
        ]),
        "</table></div>",

        "<h2>Phạm vi công việc</h2>",
        "<p>%s</p>" % _esc(scope),

        "<h2>Kết quả tổng hợp</h2>",
        _summary_cards(rows),
        _mailbox_table(rows),
    ]

    if failed:
        parts.append(
            "<h2>Hộp thư chưa đạt</h2>"
            '<p class="note">%d hộp thư dưới đây chưa hoàn tất. Nguyên nhân và '
            "hướng xử lý ghi ngay tại dòng tương ứng ở bảng trên. Thư đã chuyển "
            "được của những hộp này vẫn còn nguyên ở đích — chạy lại chỉ chuyển "
            "tiếp phần còn thiếu, không tạo thư trùng.</p>"
            "<ul>%s</ul>" % (
                len(failed),
                "".join("<li>%s</li>" % _esc(r.get("src_user")) for r in failed)))

    parts.append(_verify_section(verify_users))

    parts.append(
        "<h2>Không thuộc phạm vi</h2>"
        "<ul>%s</ul><p class=\"note\">%s</p>" % (
            "".join("<li>%s</li>" % _esc(x) for x in OUT_OF_SCOPE),
            _esc(OUT_OF_SCOPE_NOTE)))

    parts.append(_signature_block(info))

    footer = "Báo cáo được sinh tự động từ nhật ký chuyển thư, lúc %s." % _esc(now)
    if contact:
        footer += " Hỗ trợ sau bàn giao: %s." % _esc(contact)
    parts.append("<footer>%s</footer></div>" % footer)

    return ('<!doctype html><html lang="vi"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>Báo cáo bàn giao</title><style>%s</style></head>"
            "<body>%s</body></html>\n" % (_CSS, "".join(parts)))


def write_handover(path, rows: Sequence[Row],
                   verify_users: Optional[Dict[str, dict]] = None,
                   info=None, source_name: str = "", dest_name: str = "",
                   period: str = "", now: Optional[str] = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = build_html(rows, verify_users, info, source_name, dest_name, period, now)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(doc)
    return path
