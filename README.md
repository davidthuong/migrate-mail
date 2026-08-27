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

`install.sh` tải imapsync từ GitHub về `/usr/local/bin/imapsync`, rồi cài các
module Perl nó cần (apt trên Debian/Ubuntu, dnf trên RHEL/Alma, phần thiếu bù
bằng `cpanm`).

Script **không giữ danh sách module cứng**. Nó đọc thẳng các dòng `use`/`require`
trong file imapsync vừa tải, nên luôn khớp với đúng bản đang cài. Sau đó nó chạy
`imapsync --version` trong một vòng lặp: mỗi lần Perl báo `Can't locate Foo/Bar.pm`
thì cài đúng module đó rồi thử lại, tới khi imapsync chạy được. Danh sách viết tay
sẽ luôn lệch theo thời gian; đọc từ nguồn thì không.

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

## Chạy thử một mailbox trước

Đừng chạy cả danh sách ngay lần đầu. Cho đủ 20 dòng vào `users.csv`, rồi dùng
`--only` để chỉ đụng vào một hộp thư.

**Chọn hộp thư nào:** một hộp **dưới 2.5 GB** (Gmail giới hạn 2500 MB/ngày, hộp
lớn hơn không xong trong ngày) và có đủ Sent, Drafts, vài label lồng nhau — như
vậy mới kiểm được phần đổi tên folder.

```bash
U=an.nguyen@congty-cu.com

python3 mm.py doctor                      # 1. môi trường
python3 mm.py preflight --only $U         # 2. đăng nhập được cả hai đầu
python3 mm.py discover  --only $U         # 3. folder Gmail + kế hoạch chuyển
python3 mm.py discover  --dest --only $U  # 4. folder thật bên IceWarp
python3 mm.py sync --sizes --only $U       # 5. đo dung lượng, ước lượng số ngày
python3 mm.py sync --folders-only --only $U   # 6. tạo cây folder, chưa chuyển mail
python3 mm.py sync --dry --only $U        # 7. chạy khan, không ghi gì
python3 mm.py sync      --only $U         # 8. chạy thật
python3 mm.py verify    --only $U         # 9. kiểm chứng ngày tháng
```

**Vì sao có bước 6.** imapsync không mô phỏng được một folder chưa tồn tại bên
đích, nên chạy khan trên tài khoản trắng sẽ bỏ qua gần hết và cho số liệu vô
nghĩa. Tạo cây folder trước (nhanh, không đụng mail nào) thì bước 6 mới ra ước
lượng đầy đủ. Đây cũng là cách chính imapsync gợi ý trong log.

**Bước 5 trả lời câu hỏi lịch chạy.** `--sizes` chạy `--justfoldersizes` của
imapsync: nó đọc kích thước từ metadata IMAP chứ không tải thân mail, nên tốn rất
ít băng thông. Kết quả gồm tổng dung lượng, mail lớn nhất, và **số ngày cần chạy**
tính theo hạn mức 2500 MB/ngày của Gmail:

```
Mailbox                                  Mail   Dung luong  Mail lon nhat   Ngay
--------------------------------------------------------------------------------
nhi.tran@namphonggroup.com             49.720       5.0 GB        25.0 MB      3
```

Chạy bước này cho **cả 20 mailbox** ngay từ đầu để biết tổng khối lượng và lên
lịch, trước khi động vào cái nào.

Sau bước 6, chạy lại `discover --dest` là thấy toàn bộ cây folder — đối chiếu
với kế hoạch ở bước 3 xem tên có đúng không, trước khi đụng vào mail thật.

**Bước 4 là bước dễ bỏ sót nhất.** Nó liệt kê folder có sẵn trên IceWarp và cảnh
báo nếu tên trong `config.ini` không khớp:

```
CANH BAO: cac ten sau trong config.ini chua co ben IceWarp,
imapsync se TAO MOI folder trung ten:
  junk_folder    = Spam
```

Nghĩa là IceWarp đang gọi folder rác bằng tên khác (`Junk E-mail` chẳng hạn).
Nếu cứ chạy, hộp thư sẽ có **hai folder rác song song** và bộ lọc IceWarp vẫn
dùng folder cũ. Sửa `junk_folder` trong `config.ini` cho khớp rồi chạy tiếp.

**Tài khoản IceWarp mới tinh thường chỉ có `INBOX` và `Spam`.** IceWarp chỉ sinh
ra `Sent`/`Drafts`/`Trash` khi user đăng nhập và thực sự dùng. Nếu để imapsync
tạo trước, sau này IceWarp có thể tạo thêm bộ của nó với tên khác → hộp thư có
hai bộ folder. Cách chắc ăn: đăng nhập WebClient bằng tài khoản đó một lần, gửi
một mail thử, lưu một draft, xoá một mail — rồi chạy lại `discover --dest` để
xem tên thật IceWarp đặt, và sửa `config.ini` cho khớp.

### Nhiều folder Gmail đổ chung vào một folder đích

`discover` còn cảnh báo khi hai folder nguồn cùng ra một tên đích:

```
!! TRUNG TEN FOLDER DICH !!
  Drafts  <-  [Gmail]/Thư nháp, Drafts
```

Rất hay gặp với hộp thư **trước đây đã import từ Outlook vào Gmail**: bên cạnh
folder chuẩn của Gmail còn sót lại label cũ cùng công dụng (`Drafts`,
`Sent Items`, `Khác`, `Ưu tiên`...). Cả hai sẽ trộn làm một bên IceWarp.

Không mất mail, nhưng nên là quyết định có ý thức. Muốn giữ riêng thì đổi tên
label cũ trong `config.ini`:

```ini
extra_args = --regextrans2 s,^Drafts$,Drafts-cu,
```

Hoặc đổi tên đích của folder Gmail: `drafts_folder = Drafts-gmail`.

### Kiểm bằng mắt sau khi xong

Đăng nhập IceWarp WebClient bằng chính tài khoản đó:

- Cây folder có khớp với phần "GIỮ NGUYÊN" / "ĐỔI TÊN" mà `discover` in ra không?
- Sắp xếp Inbox theo ngày — mail cũ nhất có đúng là mail cũ nhất bên Gmail không?
- Mở vài mail có đính kèm, kiểm tra tiếng Việt trong tiêu đề hiển thị đúng.
- Xem folder Sent có mail không (hay bị rỗng vì map sai tên).

### Muốn chạy lại từ đầu cho sạch

Vì imapsync bỏ qua mail đã có, chạy lại sẽ không nhân đôi — nhưng cũng không dọn
cái đã sang. Muốn thử lại từ trạng thái trắng:

```bash
rm -rf state/an.nguyen@congty-cu.com     # xoá cache + dấu hoàn thành
```

rồi xoá sạch mailbox đó trong IceWarp Admin trước khi sync lần nữa.

Xong bước này, chạy phần còn lại bỏ `--only` đi là được.

---

## Quy trình chạy

### 1. `doctor` — kiểm tra môi trường

```bash
python3 mm.py doctor
```

Kiểm tra imapsync chạy được, `users.csv` parse được, thư mục ghi được. Có một
bước đáng chú ý: nó **đối chiếu mọi flag tool sẽ dùng với bảng tuỳ chọn thật của
bản imapsync đang cài** — đọc trực tiếp khối `GetOptions` trong mã nguồn, không
đọc `--help`. Lý do: imapsync có những tuỳ chọn dùng được nhưng không ghi trong
help (`--filterflags` là một ví dụ), đối chiếu với help sẽ báo động giả. Nếu
imapsync là bản đóng gói sẵn không đọc được mã nguồn, tool tự quay về dùng
`--help`.

imapsync dừng ngay khi gặp tuỳ chọn lạ, nên thà biết bây giờ còn hơn phát hiện
lúc 2 giờ sáng.

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

Thêm `--dest` để xem folder có sẵn bên IceWarp thay vì bên Gmail. Lệnh này cảnh
báo khi tên trong `config.ini` không khớp tên thật của IceWarp — nếu bỏ qua,
hộp thư sẽ có hai folder cùng công dụng nhưng khác tên.

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

### 6. `verify` — kiểm chứng ngày tháng

```bash
python3 mm.py verify
```

Đọc `INTERNALDATE` thật ở cả hai đầu, ghép theo `Message-Id`, rồi so. Chạy sau
khi sync xong mailbox đầu tiên — đừng đợi chuyển hết 20 hộp thư mới phát hiện
ngày sai. Chi tiết ở mục dưới.

### 7. Cutover

Ngày đổi MX, chạy vòng delta để nhặt mail mới về sau lần sync đầu:

```bash
python3 mm.py sync --since-days 7
```

Sau khi MX đã trỏ về IceWarp và đã ổn định, chạy thêm một lần nữa để nhặt nốt
mail đến muộn ở Gmail.

---

## Ngày tháng của mail

Triệu chứng hay gặp khi migrate: chuyển xong thì **mọi mail đều mang ngày của lúc
chuyển**, hộp thư mất hết thứ tự thời gian.

Nguyên nhân nằm ở chỗ IMAP có hai loại ngày:

| | Là gì | Ai nhìn thấy |
|---|---|---|
| `INTERNALDATE` | Ngày server gán cho mail lúc nó được đưa vào hộp thư | **Cái mail client dùng để sắp xếp và hiển thị** |
| Header `Date:` | Nằm trong thân mail, không bao giờ đổi | Chỉ hiện khi xem chi tiết |

Nếu server đích không nhận `INTERNALDATE` từ nguồn, nó sẽ gán ngày hiện tại — và
toàn bộ hộp thư nhảy về ngày migrate.

**Tool đã xử lý sẵn.** Lệnh imapsync luôn kèm `--syncinternaldates` một cách tường
minh (không dựa vào mặc định ngầm, để nhìn thấy được trong log). Có một cái bẫy
tool tránh được: `--gmail2` của imapsync tự bật `--idatefromheader` — nhưng đó là
cho chiều Gmail làm **đích**, vì Gmail bỏ qua ngày trong lệnh APPEND. Chiều
Gmail → IceWarp không dính, và tool không dùng preset đó.

### Kiểm chứng thay vì tin

```bash
python3 mm.py verify --only an.nguyen@congty-cu.com
```

Đọc `INTERNALDATE` thật ở cả hai đầu, ghép theo `Message-Id`, so từng cái. Múi
giờ khác nhau không bị báo lệch giả — `+0700 09:00` và `+0000 02:00` được hiểu
là cùng một thời điểm.

```
OK   an.nguyen@congty-cu.com   doi chieu 1843 mail, lech 0, thieu ben dich 0

Ket qua: 1843 mail doi chieu, 0 lech ngay (0.00%).
Ngay thang duoc giu nguyen tren toan bo mau kiem tra.
```

Mặc định lấy mẫu 200 mail mỗi folder, rải đều chứ không dồn về đầu. Muốn kiểm
toàn bộ: `--sample 0`.

**Chạy `verify` ngay sau khi sync xong mailbox đầu tiên.** Phát hiện ngày sai lúc
đó chỉ tốn một lần sync lại; phát hiện sau khi xong cả 20 hộp thư thì tốn cả đêm.

### Nếu ngày vẫn lệch

Đổi trong `config.ini`:

```ini
date_source = header
```

Lúc này imapsync dùng header `Date:` trong thân mail thay cho `INTERNALDATE`.
Sync lại mailbox đó rồi `verify` lần nữa.

Chọn `header` cũng hợp lý trong một trường hợp khác: nếu hộp thư Gmail trước đây
đã import từ nơi khác, `INTERNALDATE` của Gmail là ngày *import* chứ không phải
ngày thật — khi đó `header` cho ra ngày đúng hơn.

Còn nếu cả hai đều lệch thì IceWarp đang ghi đè `INTERNALDATE` lúc APPEND, phải
hỏi nhà cung cấp — không có tham số imapsync nào chữa được.

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

## Dashboard

Theo dõi 20 mailbox bằng terminal thì khó nhìn. Có giao diện web:

```bash
python3 mm.py web
```

Nó in ra một địa chỉ kèm token. Vì giao diện này **chạm vào mật khẩu**, mặc định
nó chỉ lắng nghe trên `127.0.0.1` — truy cập qua SSH tunnel từ máy bạn:

```bash
ssh -L 8765:127.0.0.1:8765 root@vps
```

Rồi mở địa chỉ server in ra. Token chỉ dùng một lần để đặt cookie, sau đó biến
khỏi thanh địa chỉ.

Trên dashboard:

- Bảng toàn bộ mailbox: kết quả lần chạy gần nhất, số mail, dung lượng, thời gian
- Chọn vài mailbox bằng checkbox, hoặc để trống để áp dụng cho tất cả
- Bấm chạy từng bước: kiểm tra đăng nhập → kế hoạch folder → tạo cây folder →
  chạy khan → chạy thật → đối chiếu ngày
- Log chạy trực tiếp, tự cuộn theo
- Form thêm mailbox, ghi thẳng vào `users.csv`; dấu ✕ ở cuối mỗi dòng để xoá
  khỏi danh sách (chỉ xoá dòng trong CSV — mail đã chuyển và log vẫn còn)

Ba nguyên tắc an toàn của giao diện này:

- **Mật khẩu không bao giờ được gửi ngược về trình duyệt.** API chỉ trả về một cờ
  cho biết ô đó đã có mật khẩu hay chưa.
- **Mỗi lúc chỉ một tác vụ.** Bấm nút thứ hai khi đang chạy sẽ bị từ chối, không
  có chuyện hai lệnh imapsync giẫm lên nhau.
- **`Chạy thật` hỏi lại trước khi chạy**, các nút còn lại đều không ghi gì.

Mở ra ngoài bằng `--host 0.0.0.0` thì được, nhưng server sẽ cảnh báo — đừng làm
vậy trừ khi có tường lửa chặn sẵn.

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
  verify.py                đối chiếu ngày tháng giữa hai đầu
  report.py                bảng terminal, CSV, HTML
  cli.py                   các lệnh con
  web.py                   dashboard: HTTP server, chạy job
  web_ui.py                trang HTML của dashboard
tests/                     210 test, không chạm mạng
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
