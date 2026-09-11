# testrig — hai Dovecot để thử `auth = master` cho ra ngô ra khoai

Bộ test tự động (`python3 -m unittest discover -s tests`) không chạm mạng, nên
có bốn thứ nó **không chứng minh được**. Rig này dựng để trả lời đúng bốn thứ
đó. Xem [mục cuối](#bốn-câu-hỏi-rig-này-sinh-ra-để-trả-lời) — đó mới là lý do
tồn tại của thư mục này, phần còn lại chỉ là thủ tục.

Rig vứt đi được: `docker compose down -v` là sạch.

Một câu hỏi thứ sáu — *đối chiếu chứng chỉ có kiểm cả tên host không* — rig này
trả lời không được, vì chứng chỉ của nó cấp đúng tên. Câu đó có phép thử riêng,
[`./tlsprobe.sh`](#thứ-sáu-mã-hoá-đúng-chứng-chỉ-của-ai), chạy 10 giây và
không cần Docker.

> Cấu hình trong đây **không phải mẫu cho server thật**: `ssl = no` và mật khẩu
> để trần. Đừng copy sang production.

## Dựng

```bash
cd testrig
sudo ./make-certs.sh --trust      # PHẢI chạy trước, xem bên dưới
docker compose up -d --build
```

Hai container, mỗi cái mở **hai** cổng:

| | Không mã hoá | TLS | Namespace | Giả làm |
|---|---|---|---|---|
| `mm-src` | 10143 | 10993 | tiền tố `INBOX.`, dấu `.` (Maildir++) | hosting cũ của khách |
| `mm-dst` | 20143 | 20993 | không tiền tố, dấu `/` | server của mình |

Namespace hai bên khác nhau **có chủ ý**: nó bắt tool phải cắt tiền tố và đổi
dấu phân cách trong lúc đang đăng nhập bằng master — đường code chưa ai chạy.

**Vì sao phải có CA riêng.** Tool đối chiếu chứng chỉ ở cả hai đường — kết nối
IMAP của chính nó và kết nối của imapsync — nên chứng chỉ tự ký sẽ bị từ chối,
đúng như nó phải thế. `make-certs.sh` dựng một CA nhỏ, ký chứng chỉ cho hai
container (SAN gồm cả `127.0.0.1`), và `--trust` cài CA đó vào trust store của
máy này. Đúng cách một hệ thống nội bộ vẫn làm.

`certs/` nằm trong `.gitignore` — khoá riêng không bao giờ được commit.

## Kiểm Dovecot trước, rồi mới đến tool

Bước này tách lỗi Dovecot khỏi lỗi của migrate-mail. Bỏ qua nó là tự chuốc một
buổi debug nhầm chỗ:

```bash
# passdb: master có mở được hộp thư người khác không
docker exec mm-src doveadm auth login 'an@cu.vn*migrate' MatKhauMasterNguon
docker exec mm-dst doveadm auth login 'an@moi.vn*migrate' MatKhauMasterDich

# userdb: hộp thư đó có chỗ chứa mail không
docker exec mm-src doveadm user an@cu.vn
docker exec mm-dst doveadm user an@moi.vn
```

Phải chạy **cả hai lệnh**, không được bỏ lệnh dưới. `doveadm auth login` chỉ
kiểm passdb; userdb hỏng thì nó vẫn in `auth succeeded` trong khi mọi lần đăng
nhập IMAP thật đều chết với `[UNAVAILABLE] Internal error occurred` — một câu
không hề nhắc tới userdb. Đây là lỗi rig này đã dính đúng một lần: file `users`
viết gọn thành `user:mật_khẩu` nên thiếu cột uid/gid/home.

`doveadm user` phải in ra `uid`, `gid`, `home`. Không ra gì thì xem
`docker logs mm-src` — dòng `missing userdb info` nằm ở đó.

Sai ở tầng passdb thì dòng đáng ngờ nhất là `master = yes` trong khối `passdb`
đầu tiên của `src/dovecot.conf`; vài bản Dovecot cần thêm
`result_success = continue`. (Dovecot 2.3.19 trên Ubuntu 24.04 thì **không** cần.)

## Đổ dữ liệu mẫu

```bash
python3 seed.py
```

Seed đăng nhập bằng **mật khẩu thật** của từng hộp thư — nó chỉ dựng sẵn đầu
bài, chưa phải phần test.

| Hộp thư | Có gì | Để lộ ra cái gì |
|---|---|---|
| `an@cu.vn` | folder tiếng Việt có dấu, folder lồng nhau, Sent/Drafts/Trash/Junk | tên UTF-7 + cây folder qua đường master |
| `binh@cu.vn` | 300 mail (`--big 2000` nếu muốn), 1 mail 12 MB | chạy đủ lâu để imapsync reconnect giữa chừng |
| `ketoan@cu.vn` | 1 mail | trường hợp biên |

## Chạy test

Đặt sẵn cho gọn (từ thư mục gốc của repo):

```bash
MM="python3 mm.py --config testrig/config.testrig.ini --users testrig/users.testrig.csv"
```

| # | Lệnh | Đạt là thấy gì |
|---|---|---|
| 1 | `$MM doctor` | `[ OK ] master nguon: migrate ...`; **không** có dòng `khong chap nhan cac flag sau: --authuser1` |
| 2 | `$MM preflight` | 3/3 đăng nhập được cả hai đầu, dù `users.testrig.csv` không có cột `src_password` |
| 3 | `$MM discover` | folder hiện đúng chữ có dấu; tiền tố `INBOX.` bị cắt khỏi tên đích |
| 4 | `$MM sync --only an@cu.vn --dry` | kế hoạch đúng, không lỗi; folder rác đổ vào **`INBOX.Junk`** chứ không phải `Spam` — `config.testrig.ini` cố tình không khai `junk_folder`, nên tên đó chỉ có thể đến từ cờ `\Junk` đọc được ở đầu đích |
| 5 | `$MM sync --only an@cu.vn` | mail sang đủ; log trong `logs/` có `<passfile>` chứ **không** có `MatKhauMasterNguon` |
| 6 | `$MM verify --only an@cu.vn` | ngày tháng khớp |
| 7 | `$MM sync` | `an` + `binh` OK, `ketoan` fail — **đọc gợi ý xem có chỉ đúng "hộp thư đích chưa tạo" không** |
| 8 | đổi `master_style = separator`, `rm -rf state/`, chạy lại #5 | kết quả y hệt #5 |
| 9 | bỏ comment khối `master` trong `[dest]`, xoá cột `dst_password` khỏi CSV, chạy lại #5 | vẫn chạy với file CSV chỉ còn hai cột địa chỉ |
| 10 | `$MM web` | ô mật khẩu **cả hai** đầu biến mất khỏi form "Thêm mailbox" |

Muốn chạy lại từ đầu cho sạch: `docker compose down -v && docker compose up -d`
rồi seed lại, và xoá `logs/` `state/` trong `testrig/`.

### Hai biến thể đáng chạy thêm

**Server không cho SASL PLAIN.** Comment `auth_master_user_separator` trong
`src/dovecot.conf` rồi `docker compose up -d --build src`. `master_style = authzid`
vẫn phải chạy (nó không phụ thuộc separator); `separator` thì phải hỏng — và
hỏng với gợi ý *"đổi master_style = separator"* ngược lại.

**Server không quảng bá SPECIAL-USE** (Courier, Dovecot đời cũ). Comment bốn
khối `mailbox ... special_use` trong `src/dovecot.conf`, build lại, chạy `discover`:
folder đặc biệt phải vẫn được nhận ra, lần này theo **tên**.

**Đầu đích không quảng bá SPECIAL-USE.** Comment bốn khối `mailbox ... special_use`
trong `dst/dovecot.conf` rồi build lại đầu đích. Giờ tool không đọc được gì bên
đích nữa nên phải lùi về tên mặc định của provider — `discover --dest` phải nói
đúng điều đó (`mac dinh cua provider, ben dich khong gan co`) và cảnh báo rằng
`Spam` sắp được tạo mới. Đây là nửa còn lại của bài #4: một bên chứng minh tool
đọc được cờ, một bên chứng minh nó biết mình *không* đọc được.

**Chạy qua cổng không mã hoá.** Mặc định của rig là TLS 993, giống mọi ca
migrate thật. Đổi hai đầu sang `port = 10143` / `20143` và `ssl = false` để thử
đường không mã hoá — vẫn phải ra cùng số mail và cùng kết quả `verify`, và
`doctor` phải kêu về việc không mã hoá.

**Chứng chỉ không tin được.** Đây là bài quan trọng nhất của phần TLS, vì nó
kiểm thứ mà mã hoá *không* làm được:

```bash
sudo rm -f /usr/local/share/ca-certificates/migrate-mail-testrig.crt
sudo update-ca-certificates --fresh
```

Giờ chứng chỉ của rig do một CA không ai tin ký. Chạy `preflight` và `sync`:
**cả hai** phải chết với `certificate verify failed` — đường IMAP của tool lẫn
đường imapsync. Rồi thêm `tls_verify = false` cho từng đầu: cả hai phải chạy
lại được, và `doctor` phải kêu mỗi lần. Tin lại CA bằng
`sudo ./make-certs.sh --trust`.

Trước khi có `tls_verify`, bài này **im lặng đi qua** — cả hai nửa đều nhận bất
kỳ chứng chỉ nào. Xem [mục dưới](#bốn-câu-hỏi-rig-này-sinh-ra-để-trả-lời).

**Mật khẩu có `%`.** Đổi `master_password` trong `config.testrig.ini` thành
`Mat%Khau%100` rồi chạy `$MM doctor`. Chỉ cần config **đọc được** là đạt —
không cần đăng nhập thành công. `configparser` mặc định coi `%` là cú pháp thay
thế và ném lỗi không hề nhắc đến mật khẩu; chỗ này đã sửa nhưng chưa ai chạy thật.

## Bốn câu hỏi rig này sinh ra để trả lời

Đã chạy thật một lượt: **Ubuntu 24.04, Dovecot 2.3.19.1, imapsync 2.314,
Python 3.12** (2026-09-08). Cả bốn đều dương tính.

**1. imapsync có thật sự gửi authzid qua `--authuser1` không?** — **Có.**
`doctor` chỉ kiểm được rằng tuỳ chọn đó *tồn tại*, khác với hành xử đúng. Chạy
thật thì dòng lệnh ra `--user1 an@cu.vn --authuser1 migrate --authmech1 PLAIN`
và 30/30 mail sang đủ, 10/10 folder, 0 lỗi. `master_style = separator` cũng
chạy, ra `--user1 an@cu.vn*migrate` và không kèm `--authuser1`.

**2. Lệnh `NAMESPACE` trả tiền tố của ai?** — **Của hộp thư khách**, đúng cái
mình cần. `INBOX.Khách hàng.Dự án A` bên nguồn thành `Khách hàng/Dự án A` bên
đích: tiền tố bị cắt, dấu phân cách đổi từ `.` sang `/`, tên có dấu nguyên vẹn.

**3. `mail_max_userip_connections` đếm theo ai?** — **Theo hộp thư đích, không
theo master user.** Hạ trần xuống `2` rồi chạy 3 mailbox song song bằng cùng
một tài khoản `migrate`: không hộp nào bị từ chối. Nghĩa là **không phải giảm
`workers` chỉ vì đang dùng `auth = master`**.

**4. Master có quyền ghi bên đích không?** — **Có**, kể cả tạo folder mới. Chạy
master ở *cả hai* đầu với `users.csv` chỉ còn hai cột địa chỉ: 331 mail,
16.6 MB, 2/2 mailbox OK, `verify` đối chiếu 331 mail lệch 0 ngày.

## Thứ năm, tìm ra khi thêm TLS vào rig

**Tool không đối chiếu chứng chỉ TLS.** Cả hai nửa. `ssl = true` cho mã hoá
nhưng không cho biết đang nói chuyện với ai — ai chen được vào đường truyền đều
đưa ra được chứng chỉ bất kỳ và nhận lấy mật khẩu. Với `auth = master`, mật
khẩu đó mở được **mọi** hộp thư trên server.

- `imaplib.IMAP4_SSL` khi không được truyền context dùng
  `ssl._create_stdlib_context()` — `check_hostname = False`,
  `verify_mode = CERT_NONE`. Tên hàm nghe như "context tiêu chuẩn".
- imapsync mặc định `SSL_verify_mode=0`, và nó in hẳn dòng đó ra log.

Chứng minh bằng cách gỡ CA khỏi trust store rồi chạy lại: **cả hai đường đều
chấp nhận**. Đã sửa — `tls_verify` mặc định bật, và cùng phép thử đó giờ làm cả
hai đường dừng lại với `certificate verify failed`.

Hai lỗi tìm ra trong lúc dựng, đã sửa trong rig này:

- File `users` viết gọn thành `user:mật_khẩu` thiếu cột uid/gid/home. Triệu
  chứng phía client là `[UNAVAILABLE] Internal error` — không nhắc gì tới
  userdb. Vì vậy phần kiểm ở trên giờ có thêm `doveadm user`.
- `seed.py` không bọc dấu nháy tên folder. Tên có khoảng trắng
  (`INBOX.Cong viec`) làm `APPEND` **treo** chứ không báo lỗi: server trả `BAD`
  thay vì `+`, còn `imaplib` ngồi đợi mãi cái `+` để gửi literal.

## Thứ sáu: mã hoá đúng chứng chỉ của ai?

`tls_verify` đặt cược vào một điều mà rig này **không** kiểm được: rằng bật đối
chiếu chứng chỉ thì tên host cũng được kiểm theo. Chứng chỉ của rig cấp đúng
tên, nên hai cách kiểm — chỉ xét chuỗi chứng chỉ, hay xét cả danh tính — đều
cho ra cùng một kết quả "chạy được". Muốn tách chúng ra thì phải có một chứng
chỉ do **đúng CA đang tin** ký nhưng cấp cho tên khác. Đó đúng là thứ một kẻ
chen đường truyền có sẵn: chứng chỉ thật, do CA công cộng ký, cho tên miền của
chính nó.

```bash
./tlsprobe.sh
```

Không cần Docker, không cần Dovecot, chạy ~10 giây; cần openssl, perl có
`IO::Socket::SSL` (imapsync bắt buộc phải có) và python3 — VPS đã chạy
`install.sh` thì đủ cả ba. Script tự dựng CA riêng dùng một lần, hai chứng chỉ
(một đúng tên, một sai tên), hai server TLS, rồi cho hai client đi qua: một cái
gọi `IO::Socket::SSL` y như imapsync, một cái dựng context y như
`discover.ssl_context()`. Exit 0 khi mọi ô khớp mong đợi.

Đã chạy (2026-09-11) trên hai máy, cùng một kết quả: **có kiểm tên**, cả hai
nửa, 10/10 ô khớp.

- VPS thật — Ubuntu 24.04 (6.8.0), `IO::Socket::SSL` 2.085, Python 3.12.3,
  OpenSSL 3.0.13, imapsync 2.314.
- Máy dev Windows, Git Bash — `IO::Socket::SSL` 2.098, OpenSSL 3.5.

Chạy trên cả hai không phải cho đủ bộ. Việc gắn callback kiểm tên tự động chỉ
có từ `IO::Socket::SSL` 1.79; bản trên VPS mới là bản thật sự đỡ lấy một cuộc
migrate, và nó không nhất thiết trùng bản trên máy dev.

| đường | chứng chỉ đúng tên | cùng CA, **sai tên** |
|---|---|---|
| `--ssl` + `SSL_verify_mode=1` | OK | từ chối: `hostname verification failed` |
| `--tls` + `SSL_verify_mode=1` | OK | từ chối: `hostname verification failed` |
| `imaplib` + `create_default_context` | OK | từ chối: `CERTIFICATE_VERIFY_FAILED` |
| cả hai khi tắt đối chiếu | OK | **OK** ← lỗ hổng, đúng như nó phải hiện ra |

Hai chi tiết đọc ra từ mã nguồn imapsync 2.314 và `IO::Socket::SSL` 2.098,
khớp với bảng trên:

- `set_ssl()` (chạy khi `--ssl1`) mặc định kèm `SSL_verifycn_scheme => 'imap'`;
  `set_tls()` (khi `--tls1`) thì không. **Cả hai vẫn kiểm tên**: hễ
  `SSL_verify_mode` bật bit `PEER` là `IO::Socket::SSL` gắn callback kiểm tên,
  không có scheme thì rơi về scheme `default`.
- `default` rộng hơn `imap` — ký tự đại diện ở mọi vị trí, IP được nằm trong
  CN. Vì vậy tool viết hẳn `SSL_verifycn_scheme=imap` ra thay vì nhận mặc định
  của imapsync: hôm nay hai thứ đó trùng nhau, nhưng một cái là lựa chọn của
  mình, cái kia là của người khác.

## Zimbra

Dựng nặng hơn Dovecot nhiều, nên để sau: xong Dovecot là biết đường đi đúng hay
sai. Zimbra chỉ khác ở chỗ `master_user` là `admin@domain` (địa chỉ đầy đủ) và
không phải sửa cấu hình server. Có sẵn một Zimbra đang chạy thì chạy #1, #2, #5
trên đó là đủ.
