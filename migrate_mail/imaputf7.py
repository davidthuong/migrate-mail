# -*- coding: utf-8 -*-
"""Giai ma modified UTF-7 (RFC 3501) de hien thi ten folder cho de doc.

Chi dung cho hien thi/bao cao. Ten dua cho imapsync LUON la ten IMAP tho.

Nguyen tac: gap du lieu hong thi giu nguyen van ban goc, tuyet doi khong
tra ve chuoi rong. Ten folder bi mat trong bao cao nguy hiem hon ten xau.
"""

from __future__ import annotations

import base64

SHIFT = "&"
UNSHIFT = "-"


def decode(raw: str) -> str:
    if SHIFT not in raw:
        return raw

    out = []
    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch != SHIFT:
            out.append(ch)
            i += 1
            continue

        end = raw.find(UNSHIFT, i + 1)
        if end == -1:
            # Doan shift khong duoc dong -> giu nguyen phan con lai
            out.append(raw[i:])
            break

        chunk = raw[i + 1:end]
        if chunk == "":
            out.append(SHIFT)          # "&-" la cach viet escape cua dau &
        else:
            decoded = _decode_chunk(chunk)
            out.append(decoded if decoded is not None else raw[i:end + 1])
        i = end + 1

    return "".join(out)


def _decode_chunk(chunk: str):
    """Giai ma mot doan base64 bien the. Tra ve None neu khong hop le."""
    b64 = chunk.replace(",", "/")
    b64 += "=" * (-len(b64) % 4)
    try:
        # validate=True rat quan trong: mac dinh b64decode BO QUA ky tu ngoai
        # bang chu cai, nen rac nhu "!!!" se ra chuoi rong ma khong bao loi.
        data = base64.b64decode(b64, validate=True)
    except Exception:
        return None
    if not data or len(data) % 2:
        return None                    # UTF-16BE luon di theo cap byte
    try:
        return data.decode("utf-16-be")
    except UnicodeDecodeError:
        return None
