# testrig — hai Dovecot để thử `auth = master` cho ra ngô ra khoai

Bộ test tự động (`python3 -m unittest discover -s tests`) không chạm mạng, nên
có bốn thứ nó **không chứng minh được**. Rig này dựng để trả lời đúng bốn thứ
đó. Xem [mục cuối](#bốn-câu-hỏi-rig-này-sinh-ra-để-trả-lời) — đó mới là lý do
tồn tại của thư mục này, phần còn lại chỉ là thủ tục.

Rig vứt đi được: `docker compose down -v` là sạch.

> Cấu hình trong đây **không phải mẫu cho server thật**: `ssl = no` và mật khẩu
> để trần. Đừng copy sang production.

## Dựng

```bash
cd testrig && docker compose up -d --build
```

Hai container:

| | Cổng | Namespace | Giả làm |
|---|---|---|---|
| `mm-src` | 10143 | tiền tố `INBOX.`, dấu `.` (Maildir++) | hosting cũ của khách |
| `mm-dst` | 20143 | không tiền tố, dấu `/` | server của mình |

Namespace hai bên khác nhau **có chủ ý**: nó bắt tool phải cắt tiền tố và đổi
dấu phân cách trong lúc đang đăng nhập bằng master — đường code chưa ai chạy.

## Kiểm Dovecot trước, rồi mới đến tool

Bước này tách lỗi Dovecot khỏi lỗi của migrate-mail. Bỏ qua nó là tự chuốc một
buổi debug nhầm chỗ:

```bash
docker exec mm-src doveadm auth login 'an@cu.vn*migrate' MatKhauMasterNguon
docker exec mm-dst doveadm auth login 'an@moi.vn*migrate' MatKhauMasterDich
```

Cả hai phải in `passdb: ... auth succeeded`. Không qua thì vấn đề nằm trong
`src/dovecot.conf` — dòng đáng ngờ nhất là `master = yes` trong khối `passdb`
đầu tiên; vài bản Dovecot cần thêm `result_success = continue` ở đó.

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
| 4 | `$MM sync --only an@cu.vn --dry` | kế hoạch đúng, không lỗi |
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

**Mật khẩu có `%`.** Đổi `master_password` trong `config.testrig.ini` thành
`Mat%Khau%100` rồi chạy `$MM doctor`. Chỉ cần config **đọc được** là đạt —
không cần đăng nhập thành công. `configparser` mặc định coi `%` là cú pháp thay
thế và ném lỗi không hề nhắc đến mật khẩu; chỗ này đã sửa nhưng chưa ai chạy thật.

## Bốn câu hỏi rig này sinh ra để trả lời

1. **imapsync có thật sự gửi authzid qua `--authuser1` không?** `doctor` chỉ
   kiểm được rằng tuỳ chọn đó *tồn tại* trong bản đang cài — khác với *hành xử
   đúng*. Bước #5 trả lời. Nếu hỏng, `master_style = separator` là đường vòng
   có sẵn, không phải sửa code.
2. **Lệnh `NAMESPACE` trả tiền tố của ai?** Khi đăng nhập bằng master, nó trả
   namespace của hộp thư *khách* hay của *master*? Trả nhầm thì folder mọc sai
   chỗ, và sai một cách im lặng. Bước #3 phát hiện.
3. **`mail_max_userip_connections` đếm theo ai?** Nếu Dovecot đếm theo master
   user thay vì theo từng hộp thư thì `workers = 3` chạm trần sớm hơn hẳn — cái
   này ảnh hưởng thẳng tới lịch chạy của một ca migrate thật. Bước #7 với 3
   luồng song song sẽ lộ.
4. **Master có quyền ghi bên đích không?** Đọc được không có nghĩa là `APPEND`
   và tạo folder được. Bước #9.

## Zimbra

Dựng nặng hơn Dovecot nhiều, nên để sau: xong Dovecot là biết đường đi đúng hay
sai. Zimbra chỉ khác ở chỗ `master_user` là `admin@domain` (địa chỉ đầy đủ) và
không phải sửa cấu hình server. Có sẵn một Zimbra đang chạy thì chạy #1, #2, #5
trên đó là đủ.
