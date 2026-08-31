# -*- coding: utf-8 -*-
"""Lay OAuth2 access token cua Microsoft de doc mailbox qua IMAP.

Vi sao phai co: Microsoft da tat basic auth tren phan lon tenant Microsoft 365.
Khong con cach nao dang nhap IMAP bang mat khau nguoi dung nua, va cung khong
co "app password" nhu Google. Duong con lai la dang ky mot ung dung tren Entra
ID (Azure AD), cho no quyen doc mailbox toan tenant, roi dung token cua ung
dung do de dang nhap thay tung mailbox.

Luong chay (client credentials, khong co nguoi dung bam nut):

    POST https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token
         grant_type=client_credentials
         scope=https://outlook.office365.com/.default
    -> {"access_token": "...", "expires_in": 3599}

Token dung chung cho MOI mailbox trong tenant; danh tinh mailbox nam o ten
dang nhap khi lam SASL XOAUTH2, khong nam trong token. Nho vay chay 20 mailbox
song song van chi can mot token.

Chuan bi mot lan tren tenant nguon (khach hang phai lam, khong tu lam ho duoc):
  1. Entra ID > App registrations > New registration.
  2. API permissions > APIs my organization uses > Office 365 Exchange Online
     > Application permissions > IMAP.AccessAsApp > Grant admin consent.
  3. Certificates & secrets > New client secret.
  4. Exchange Online PowerShell, dang ky service principal cho app do:
       New-ServicePrincipal -AppId <client_id> -ServiceId <object_id>
     Thieu buoc nay thi token lay ve van hop le nhung IMAP tra ve
     AUTHENTICATE failed.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional

DEFAULT_AUTHORITY = "https://login.microsoftonline.com"
DEFAULT_SCOPE = "https://outlook.office365.com/.default"

# Xin token moi truoc khi het han bao nhieu giay. Mot lan sync co the chay hang
# gio, va imapsync doc file token luc khoi dong tung mailbox.
REFRESH_MARGIN = 300


class OAuthError(Exception):
    pass


@dataclass
class OAuthConf:
    tenant: str = ""
    client_id: str = ""
    client_secret: str = ""
    scope: str = DEFAULT_SCOPE
    authority: str = DEFAULT_AUTHORITY

    def missing(self) -> List[str]:
        return [name for name in ("tenant", "client_id", "client_secret")
                if not getattr(self, name).strip()]

    @property
    def configured(self) -> bool:
        return not self.missing()

    @property
    def token_url(self) -> str:
        return "%s/%s/oauth2/v2.0/token" % (
            self.authority.rstrip("/"), urllib.parse.quote(self.tenant.strip()))


def request_token(conf: OAuthConf, timeout: int = 30) -> "tuple":
    """Goi Microsoft lay token. Tra ve (token, so_giay_con_hieu_luc)."""
    missing = conf.missing()
    if missing:
        raise OAuthError(
            "thieu cau hinh oauth trong config.ini: %s" % ", ".join(missing))

    data = urllib.parse.urlencode({
        "client_id": conf.client_id.strip(),
        "client_secret": conf.client_secret,
        "scope": conf.scope.strip() or DEFAULT_SCOPE,
        "grant_type": "client_credentials",
    }).encode("utf-8")
    req = urllib.request.Request(
        conf.token_url, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise OAuthError(_http_error(exc))
    except urllib.error.URLError as exc:
        raise OAuthError("khong goi duoc %s: %s" % (conf.token_url, exc.reason))
    except (ValueError, OSError) as exc:
        raise OAuthError("loi khi lay token: %s" % exc)

    token = payload.get("access_token")
    if not token:
        raise OAuthError("Microsoft tra ve tra loi khong co access_token: %s"
                         % json.dumps(payload)[:300])
    try:
        expires = int(payload.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires = 3600
    return token, expires


def _http_error(exc: "urllib.error.HTTPError") -> str:
    """Boc thong bao that cua Microsoft ra khoi tra loi loi.

    Ma AADSTS trong error_description la thu duy nhat tra cuu duoc, nen phai
    giu nguyen thay vi chi in "HTTP 401".
    """
    try:
        body = json.loads(exc.read().decode("utf-8", "replace"))
    except Exception:
        return "Microsoft tu choi cap token (HTTP %s)" % exc.code
    detail = (body.get("error_description") or body.get("error")
              or json.dumps(body))
    detail = " ".join(str(detail).split())
    return "Microsoft tu choi cap token (HTTP %s): %s" % (exc.code, detail[:400])


class TokenSource:
    """Giu mot token va tu xin lai truoc khi no het han. An toan da luong."""

    def __init__(self, conf: OAuthConf,
                 fetch: Optional[Callable[[OAuthConf], "tuple"]] = None,
                 now: Callable[[], float] = time.time):
        self.conf = conf
        self._fetch = fetch or request_token
        self._now = now
        self._lock = threading.Lock()
        self._token = ""
        self._expires_at = 0.0

    def token(self) -> str:
        with self._lock:
            if self._token and self._now() < self._expires_at:
                return self._token
            token, expires = self._fetch(self.conf)
            self._token = token
            self._expires_at = self._now() + max(60, expires - REFRESH_MARGIN)
            return self._token

    def invalidate(self) -> None:
        with self._lock:
            self._token = ""
            self._expires_at = 0.0


_SOURCES: "dict" = {}
_SOURCES_LOCK = threading.Lock()


def source_for(conf: OAuthConf) -> TokenSource:
    """TokenSource dung chung cho moi mailbox cua cung mot app dang ky.

    Token cua client_credentials khong gan voi mailbox nao ca, nen 20 mailbox
    chay song song van chi can mot token va mot lan goi Microsoft.
    """
    key = (conf.authority, conf.tenant, conf.client_id, conf.scope)
    with _SOURCES_LOCK:
        src = _SOURCES.get(key)
        if src is None or src.conf.client_secret != conf.client_secret:
            src = TokenSource(conf)
            _SOURCES[key] = src
        return src


def xoauth2(user: str, token: str) -> bytes:
    """Chuoi SASL XOAUTH2. imaplib tu ma hoa base64 nen tra ve bytes tho."""
    return ("user=%s\x01auth=Bearer %s\x01\x01" % (user, token)).encode("utf-8")
