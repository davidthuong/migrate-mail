# Mở dashboard ra ngoài bằng Caddy

Thư mục này có hai file để chạy dashboard như một dịch vụ, vào được từ bất kỳ
đâu qua HTTPS:

| File | Việc |
|---|---|
| [`Caddyfile`](Caddyfile) | Reverse proxy: HTTPS + mật khẩu + lọc IP |
| [`postboat.service`](postboat.service) | Chạy dashboard như dịch vụ systemd |

---

## Đọc cái này trước

`web.py` là `http.server` của thư viện chuẩn: một token cookie duy nhất, không
HTTPS, không giới hạn số lần thử, không có khái niệm nhiều người dùng. Nó được
viết để nghe trên `127.0.0.1` và vào qua SSH tunnel.

**Và nó giữ mật khẩu hộp thư của khách hàng anh.**

Các file ở đây không sửa được bản chất đó. Chúng dựng ba lớp đứng trước:

1. **Lọc IP** — ngoài danh sách thì bị cắt, không được mời nhập gì
2. **Mật khẩu** HTTP basic, băm bcrypt
3. **HTTPS** thật, chứng chỉ Caddy tự xin và tự gia hạn

Rủi ro còn lại, nói thẳng: nếu ai đó qua được ba lớp đó, họ có toàn bộ mật khẩu
hộp thư trong `users.csv` và có nút `Chạy thật` — tức là ghi được vào hệ thống
mail của khách. **SSH tunnel vẫn an toàn hơn** và không cần file nào ở đây. Chỉ
dùng cách này khi việc phải mở tunnel mỗi lần thực sự cản trở công việc.

Khi cuộc migrate xong, gỡ nó đi — xem mục cuối trang.

---

## Các bước

### 1. Trỏ tên miền

Tạo bản ghi `A` (và `AAAA` nếu có IPv6) cho `mm.congty.vn` về đúng IP của VPS.
Làm **trước** khi khởi động Caddy: nó xin chứng chỉ bằng cách chứng minh mình
giữ tên miền đó, nên DNS phải phân giải đúng từ trước.

Kiểm tra:

```bash
dig +short mm.congty.vn
```

### 2. Cài Caddy

Theo hướng dẫn chính thức cho bản phân phối của anh:
<https://caddyserver.com/docs/install>. Bản trong kho apt/dnf của hệ điều hành
thường quá cũ — chỉ thị `basic_auth` mới có tên này từ **Caddy 2.8**; bản cũ hơn
gọi nó là `basicauth`.

Kiểm tra phiên bản:

```bash
caddy version
```

### 3. Sinh băm mật khẩu

```bash
caddy hash-password
```

Nó hỏi mật khẩu hai lần rồi in ra chuỗi bắt đầu bằng `$2a$`. Copy nguyên chuỗi
đó. Caddy không nhận mật khẩu thô.

### 4. Sửa Caddyfile

Copy `Caddyfile` sang `/etc/caddy/Caddyfile` rồi sửa ba chỗ:

- `mm.congty.vn` → tên miền thật
- `<BAM-MAT-KHAU>` → chuỗi `$2a$...` vừa sinh
- `<IP-CUA-BAN>` → dải IP được phép vào, ví dụ `14.161.0.0/16`

Xem IP hiện tại của mình:

```bash
curl -s https://api.ipify.org
```

### 5. Tường lửa: chỉ mở 80 và 443

Đây là bước dễ quên nhất, và quên thì **ba lớp bảo vệ bị đi vòng hoàn toàn** —
người ta gõ thẳng `http://<ip-vps>:8765` là vào, không qua Caddy. Không có gì
báo cả.

```bash
ufw allow 80,443/tcp && ufw deny 8765/tcp && ufw enable
```

Cổng 80 cần cho Let's Encrypt xác thực và cho việc chuyển hướng sang HTTPS.

### 6. Chạy dashboard như dịch vụ

Tạo user riêng và đặt tool vào `/opt`:

```bash
useradd -r -s /usr/sbin/nologin migrate && chown -R migrate: /opt/postboat
```

Copy `postboat.service` sang `/etc/systemd/system/`, sửa `User=` và
`WorkingDirectory=` cho khớp, rồi:

```bash
systemctl daemon-reload && systemctl enable --now postboat
```

> Nếu tool nằm trong `/home/...` thì phải bỏ dòng `ProtectHome=read-only`,
> không thì `logs/` và `state/` không ghi được.

### 7. Kiểm cấu hình rồi nạp

**Luôn `validate` trước `reload`.** Cấu hình sai mà reload thẳng thì Caddy giữ
bản cũ nhưng không phải lúc nào cũng nói rõ vì sao.

```bash
caddy validate --config /etc/caddy/Caddyfile
```

```bash
systemctl reload caddy
```

### 8. Lấy token và đăng nhập

Token in ra lúc dashboard khởi động:

```bash
journalctl -u postboat | grep '?t='
```

Nó in ra địa chỉ dạng `http://127.0.0.1:8765/?t=<token>`. Giữ nguyên phần
`/?t=<token>`, đổi phần đầu thành tên miền:

```
https://mm.congty.vn/?t=<token>
```

Token dùng một lần để đặt cookie rồi biến khỏi thanh địa chỉ. Mất token thì:

```bash
systemctl restart postboat
```

Token mới sinh mỗi lần khởi động — và đó cũng là cách đóng cửa nhanh nhất nếu
nghi có chuyện, vì restart làm mọi cookie đang có hết hiệu lực.

---

## Không có IP tĩnh

Mạng nhà đổi IP thì lớp 1 thành ra vướng chân chính mình. Ba lựa chọn, xếp theo
mức an toàn:

**Tốt nhất — WireGuard.** Dựng VPN trên VPS, cho phép dải IP của VPN thay vì IP
nhà. Không đổi bao giờ, và mạnh hơn cả ba lớp ở đây cộng lại.

**Chấp nhận được — dải của nhà mạng.** Cho phép cả dải `/16` của FPT hoặc
Viettel mà anh đang dùng. Rộng hơn nhiều, nhưng vẫn cắt được toàn bộ phần còn
lại của thế giới.

**Cuối cùng — bỏ lớp IP.** Xoá hai dòng `@ngoai` và `abort @ngoai`. Lúc đó mật
khẩu là thứ **duy nhất** đứng giữa Internet và mật khẩu hộp thư của khách. Nếu
chọn cách này thì đặt mật khẩu dài — 20 ký tự trở lên, sinh bằng máy, không phải
mật khẩu anh nhớ được.

---

## Xong việc thì gỡ đi

Một dashboard mở ra Internet mà không ai còn dùng là một cánh cửa không ai còn
nhìn. Cuộc migrate xong thì:

```bash
systemctl disable --now postboat caddy
```

Rồi xoá `users.csv` — nó chứa mật khẩu hộp thư của khách và không còn việc gì
nữa:

```bash
shred -u /opt/postboat/users.csv
```

Log và báo cáo giữ lại được: chúng không chứa mật khẩu.
