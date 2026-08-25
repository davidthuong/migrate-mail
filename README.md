# migrate-mail

Tool migrate mailbox từ **Google (Gmail / Workspace) sang IceWarp**, dựng trên nền
[imapsync](https://github.com/imapsync/imapsync).

imapsync lo phần chuyển mail. Tool này lo phần còn lại: chạy nhiều mailbox song
song, xử lý mấy cái quái của Gmail, che giấu mật khẩu, và cho ra báo cáo đọc được.

Chỉ dùng thư viện chuẩn của Python 3 — không cần `pip install` gì cả.

---

## Vì sao không gọi thẳng imapsync

Ba thứ dễ làm hỏng một cuộc migrate Gmail, tool xử lý sẵn:

**1. Gmail dùng label, không phải folder.** Một mail gắn 3 label sẽ xuất hiện ở 3
nơi, và xuất hiện thêm lần nữa trong `All Mail`. Copy nguyên xi sang IceWarp sẽ
làm dung lượng phình gấp mấy lần. Tool tự loại `All Mail`, `Important`, `Starred`.

**2. Tên folder Gmail đổi theo ngôn ngữ account.** Cùng một hộp thư có thể là
`[Gmail]/Sent Mail`, `[Gmail]/Thư đã gửi`, hay `[Gmail]/Gesendet`. Mọi hướng dẫn
imapsync trên mạng đều hardcode tên tiếng Anh — gặp account tiếng Việt là im lặng
copy nhầm `All Mail`. Tool đăng nhập IMAP trước, đọc cờ SPECIAL-USE
(`\All`, `\Sent`, `\Drafts`, `\Trash`, `\Junk`) rồi mới dựng lệnh. Không đoán tên.

Nếu không đọc được folder của một mailbox, tool **bỏ hẳn mailbox đó** chứ không
chạy mù — chạy mù rủi ro hơn nhiều so với chạy thiếu.

**3. Mật khẩu.** Tham số dòng lệnh hiện trong `ps aux` cho mọi user trên VPS.
Tool ghi mật khẩu ra file tạm quyền `0600`, truyền qua `--passfile1/2`, và xoá
sau khi chạy xong. Log ghi lại lệnh nhưng che đường dẫn passfile.

---

## Cài trên VPS

```bash
git clone <repo> migrate-mail && cd migrate-mail
chmod +x install.sh mm.py
sudo ./install.sh
```

`install.sh` cài các module Perl imapsync cần (apt trên Debian/Ubuntu, dnf trên
RHEL/Alma, phần thiếu thì bù bằng `cpanm`), tải imapsync từ GitHub về
`/usr/local/bin/imapsync`, rồi chạy thử `--version` để chắc chắn nó lên được.

Muốn ghim phiên bản imapsync cụ thể:

```bash
sudo IMAPSYNC_REF=v2.290 ./install.sh
```

---

## Chuẩn bị phía Google

Mỗi mailbox cần một **App Password 16 ký tự** — không dùng được mật khẩu đăng nhập.

1. Bật xác thực 2 bước cho account (bắt buộc, không bật thì mục App Password
   không hiện ra).
2. Vào <https://myaccount.google.com/apppasswords>, tạo password mới, copy 16 ký tự.
3. Nếu là Google Workspace: admin phải bật IMAP cho tổ chức —
   **Admin console → Apps → Google Workspace → Gmail → End User Access → IMAP**.
   Tắt ở cấp tổ chức thì không App Password nào cứu được.

Google hiển thị password dạng `abcd efgh ijkl mnop`. Dán vào CSV kèm khoảng trắng
cũng được, tool tự bỏ.

## Chuẩn bị phía IceWarp

- Tạo sẵn toàn bộ tài khoản đích trước khi chạy.
- Đặt quota đủ lớn. Ước lượng bằng dung lượng Gmail của user, cộng thêm ~20% dự phòng.
- Kiểm tra giới hạn kích thước mail của IceWarp. Nếu Gmail có mail lớn hơn giới
  hạn đó, đặt `maxsize` trong `config.ini` để bỏ qua chúng — nếu không imapsync
  sẽ báo lỗi từng cái một cho tới khi chạm `errorsmax` và dừng cả mailbox.
- Mở port 993 từ IP của VPS.

---

## Cấu hình

```bash
cp config.example.ini config.ini   && vi config.ini
cp users.example.csv  users.csv    && vi users.csv
chmod 600 users.csv
```

`users.csv`:

```csv
src_user,src_password,dst_user,dst_password
an.nguyen@congty-cu.com,abcd efgh ijkl mnop,an.nguyen@congty.vn,MatKhauIceWarp1
```

`config.ini` — ít nhất phải sửa `[dest] host`. Mọi tuỳ chọn đều có chú thích
trong `config.example.ini`.

> `config.ini` và `users.csv` đã nằm trong `.gitignore`. Đừng commit chúng.

---

## Quy trình chạy

### 1. `doctor` — kiểm tra môi trường

```bash
python3 mm.py doctor
```

Kiểm tra imapsync chạy được, `users.csv` parse được, thư mục ghi được. Có một
bước đáng chú ý: nó **đối chiếu mọi flag tool sẽ dùng với `imapsync --help` của
bản đang cài**. Bản imapsync khác nhau có bộ flag khác nhau; thà biết ngay bây
giờ còn hơn phát hiện lúc 2 giờ sáng.

### 2. `preflight` — thử đăng nhập cả hai đầu

```bash
python3 mm.py preflight
```

Đăng nhập IMAP cả Gmail lẫn IceWarp cho từng dòng trong CSV. Đây là bước bắt lỗi
sai mật khẩu, thiếu tài khoản, sai domain — rẻ và nhanh. Chạy nó trước.

### 3. `discover` — xem kế hoạch chuyển đổi

```bash
python3 mm.py discover
```

In ra folder nào bị **bỏ qua**, folder nào **đổi tên**, folder nào **giữ nguyên**,
cho từng mailbox. Đọc kỹ phần "BỎ QUA" — đó là những gì sẽ không sang IceWarp.

### 4. `sync --dry` — chạy thử

```bash
python3 mm.py sync --dry
```

imapsync duyệt hết mọi thứ nhưng không ghi gì vào IceWarp. Xác nhận số lượng mail
khớp với mong đợi trước khi chạy thật.

### 5. `sync` — chạy thật

```bash
python3 mm.py sync
```

Chạy được, dừng được, chạy lại được. imapsync bỏ qua mail đã có bên đích nên
chạy lại **không** nhân đôi dữ liệu. Nếu đứt giữa chừng, chạy lại đúng lệnh đó.

Dùng `screen` hoặc `tmux` — lần chạy đầu có thể kéo dài nhiều giờ:

```bash
tmux new -s migrate
python3 mm.py sync
```

### 6. Cutover

Ngày đổi MX, chạy vòng delta để nhặt mail mới về sau lần sync đầu:

```bash
python3 mm.py sync --since-days 7
```

Sau khi MX đã trỏ về IceWarp và đã ổn định, chạy thêm một lần nữa để nhặt nốt
mail đến muộn ở Gmail.

---

## Giới hạn của Gmail — cái này quyết định lịch chạy

Google giới hạn **2500 MB/ngày cho mỗi account** qua IMAP download. Vượt thì
account bị khoá IMAP, thường 1 giờ, có thể tới 24 giờ.

Hệ quả thực tế:

- **Hộp thư >2.5 GB không thể migrate xong trong một ngày.** Không có cách lách.
  Chạy nhiều ngày, mỗi ngày chạy lại cùng lệnh `sync`.
- Bắt đầu sync đầy đủ **sớm hơn ngày cutover vài ngày**, đừng để đêm cuối.
- Giới hạn tính theo từng account, nên nhiều mailbox chạy song song không cộng dồn.
- Gmail cũng chỉ cho tối đa 15 kết nối IMAP đồng thời cho một account.

Khi đụng giới hạn, tool nhận ra và nói rõ trong báo cáo thay vì trả về một mã lỗi khó hiểu.

Nguồn: [Gmail bandwidth limits — Google Workspace Admin Help](https://knowledge.workspace.google.com/admin/gmail/gmail-bandwidth-limits)

---

## Báo cáo

Mỗi lần `sync` sinh ra:

| File | Dùng để làm gì |
|---|---|
| `logs/<user>.sync.<thời-điểm>.log` | Toàn bộ output imapsync của một mailbox |
| `logs/report-<thời-điểm>.csv` | Mở bằng Excel |
| `logs/report-<thời-điểm>.html` | Gửi cho sếp |
| `state/runs/<thời-điểm>.json` | Để lệnh `report` đọc lại |

```bash
python3 mm.py report              # xem lại lần chạy gần nhất
python3 mm.py report --list       # liệt kê các lần đã chạy
python3 mm.py report --out bao-cao.html
```

Mailbox lỗi sẽ kèm gợi ý xử lý cụ thể, không phải mã lỗi trần.

---

## Các lệnh khác

```bash
python3 mm.py sync --only an@cu.com,binh@cu.com   # chỉ vài mailbox
python3 mm.py sync --resume                        # bỏ qua mailbox đã xong
python3 mm.py sync --workers 5                     # ghi đè số luồng song song
python3 mm.py sync --since-days 3                  # chỉ mail mới hơn 3 ngày
```

`--resume` dựa vào file đánh dấu trong `state/<user>/done.marker`. Muốn ép chạy
lại một mailbox thì xoá file đó đi.

---

## Xử lý sự cố

Tool tự dịch các lỗi hay gặp thành việc cần làm. Bảng dưới là để tra nhanh:

| Triệu chứng | Nguyên nhân |
|---|---|
| `Invalid credentials` phía Gmail | Đang dùng mật khẩu thường thay vì App Password |
| `Application-specific password required` | Account bật 2FA, phải dùng App Password |
| `Web login required` | Google chặn; đăng nhập Gmail bằng trình duyệt một lần rồi thử lại |
| `Bandwidth limit` / `[LIMIT]` | Đụng giới hạn 2500 MB/ngày; chờ reset rồi chạy lại |
| `Too many simultaneous connections` | Quá 15 kết nối trên một account; giảm `workers` |
| `[OVERQUOTA]` | Hộp thư IceWarp đầy |
| `Message too big` | Vượt giới hạn kích thước của IceWarp; đặt `maxsize` |
| `[TRYCREATE]` | Không tạo được folder bên IceWarp — thường do trùng tên với folder PIM (Contacts, Calendar, Tasks, Notes) |
| `Can't locate ...pm in @INC` | Thiếu module Perl; chạy lại `install.sh` hoặc `cpanm <Module>` |

Nếu cần đào sâu, xem file log của mailbox đó — nó chứa nguyên văn output imapsync.
Muốn chi tiết hơn nữa, thêm vào `config.ini`:

```ini
extra_args = --debugimap
```

### Folder bị đặt tên lạ ở IceWarp

Nếu tên folder dịch chưa vừa ý, dùng `--regextrans2` của imapsync qua `extra_args`.
Ví dụ dồn mọi label vào một cây `Gmail/`:

```ini
extra_args = --regextrans2 s,^(?!INBOX|Sent|Drafts|Trash|Spam),Gmail/$1,
```

---

## Cấu trúc mã nguồn

```
mm.py                      điểm vào
migrate_mail/
  config.py                đọc config.ini
  users.py                 đọc users.csv, chuẩn hoá app password
  discover.py              đọc folder Gmail, dựng kế hoạch chuyển đổi
  imaputf7.py              giải mã tên folder để hiển thị
  runner.py                dựng và chạy lệnh imapsync, đọc kết quả
  hints.py                 dịch lỗi imapsync thành việc cần làm
  report.py                bảng terminal, CSV, HTML
  cli.py                   các lệnh con
tests/                     91 test, không chạm mạng
install.sh                 cài imapsync + module Perl
```

Chạy test:

```bash
python3 -m unittest discover -s tests
```

Test dùng một imapsync giả và dữ liệu folder mẫu, nên chạy được ở bất cứ đâu,
không cần mạng và không cần tài khoản thật.

---

## Ghi chú

- imapsync là phần mềm tự do (giấy phép NOLIMIT); tác giả có bán bản build sẵn
  và dịch vụ hỗ trợ. `install.sh` lấy mã nguồn từ repo GitHub chính thức.
- Tool này chỉ chuyển **mail**. Lịch, danh bạ, task của Google không đi qua IMAP —
  phải export/import riêng.
- Bộ lọc, chữ ký, chuyển tiếp bên Gmail cũng không được chuyển; phải tạo lại
  thủ công trên IceWarp.
