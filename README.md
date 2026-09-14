# migrate-mail

Tool migrate mailbox **từ nhà cung cấp mail này sang nhà cung cấp khác**, dựng
trên nền [imapsync](https://github.com/imapsync/imapsync).

Nguồn được hỗ trợ sẵn: Gmail / Google Workspace, Microsoft 365 / Exchange
Online, Exchange tự dựng, cPanel / DirectAdmin / Plesk (Dovecot), Courier,
Zimbra, Yahoo, Zoho, iCloud, và IMAP chung cho những nơi còn lại. Đích mặc định
là IceWarp, nhưng bất kỳ server IMAP nào cũng làm đích được.

imapsync lo phần chuyển mail. Tool này lo phần còn lại: chạy nhiều mailbox song
song, xử lý cái quái riêng của từng nhà cung cấp, che giấu mật khẩu, và cho ra
báo cáo đọc được.

Chỉ dùng thư viện chuẩn của Python 3 — không cần `pip install` gì cả.

```bash
python3 mm.py providers          # xem danh sách nguồn và việc phải chuẩn bị
python3 mm.py providers m365     # xem chi tiết một nguồn
```

---

## Vì sao không gọi thẳng imapsync

Bốn thứ dễ làm hỏng một cuộc migrate, tool xử lý sẵn:

**1. Mỗi nguồn có folder không phải mail của riêng nó.** Gmail dùng label chứ
không phải folder: một mail gắn 3 label xuất hiện ở 3 nơi, và thêm lần nữa trong
`All Mail` — copy nguyên xi sẽ làm dung lượng phình gấp mấy lần. Exchange có
`Outbox` và `Sync Issues`. Zimbra bày cả `Contacts`, `Calendar`, `Chats` ra
đường IMAP. Tool biết folder nào của nhà cung cấp nào và bỏ qua chúng, có ghi rõ
lý do trong `discover`.

**2. Tên folder đặc biệt thì mỗi nơi một kiểu, lại đổi theo ngôn ngữ account.**
Cùng một hộp thư có thể gọi folder gửi đi là `[Gmail]/Sent Mail`,
`[Gmail]/Thư đã gửi`, `Sent Items`, hay `INBOX.Sent`. Mọi hướng dẫn imapsync
trên mạng đều hardcode tên tiếng Anh — gặp account tiếng Việt là im lặng copy
nhầm. Tool đăng nhập IMAP trước, đọc cờ SPECIAL-USE (`\Sent`, `\Drafts`,
`\Trash`, `\Junk`, `\Archive`) rồi mới dựng lệnh; server nào không gắn cờ
(Courier, Exchange đời cũ) thì đối chiếu theo bảng tên của nhà cung cấp đó.

Nếu không đọc được folder của một mailbox, tool **bỏ hẳn mailbox đó** chứ không
chạy mù — chạy mù rủi ro hơn nhiều so với chạy thiếu.

**3. Cách đăng nhập không giống nhau.** Gmail/Yahoo/Zoho/iCloud bắt buộc app
password. Microsoft 365 đã tắt basic auth trên phần lớn tenant — ở đó không có
mật khẩu nào dùng được, phải đi bằng OAuth2 với một app đăng ký trên Entra ID.
Tool tự lấy và làm mới token, không cần mật khẩu của từng user.

**4. Mật khẩu.** Tham số dòng lệnh hiện trong `ps aux` cho mọi user trên VPS.
Tool ghi mật khẩu (và access token) ra file tạm quyền `0600`, truyền qua
`--passfile1/2` hoặc `--oauthaccesstoken1`, và xoá sau khi chạy xong. Log ghi
lại lệnh nhưng che đường dẫn các file đó.

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

## Chuẩn bị phía nguồn

Khai báo nguồn trong `config.ini`:

```ini
[source]
provider = gmail        ; hoặc m365, dovecot, zimbra, courier, yahoo, zoho, icloud, exchange, imap
```

`provider` quyết định ba thứ: host mặc định, cách nhận ra folder đặc biệt, và
folder nào không phải mail nên bỏ qua. Chạy `python3 mm.py providers <tên>` để
xem việc phải chuẩn bị cho từng nguồn. Dưới đây là phần cần đọc kỹ.

### Gmail / Google Workspace

Mỗi mailbox cần một **App Password 16 ký tự** — không dùng được mật khẩu đăng nhập.

1. Bật xác thực 2 bước cho account (bắt buộc, không bật thì mục App Password
   không hiện ra).
2. Vào <https://myaccount.google.com/apppasswords>, tạo password mới, copy 16 ký tự.
3. Nếu là Google Workspace: admin phải bật IMAP cho tổ chức —
   **Admin console → Apps → Google Workspace → Gmail → End User Access → IMAP**.
   Tắt ở cấp tổ chức thì không App Password nào cứu được.

Google hiển thị password dạng `abcd efgh ijkl mnop`. Dán vào CSV kèm khoảng trắng
cũng được, tool tự bỏ.

### Microsoft 365 / Exchange Online

Phần lớn tenant đã tắt basic auth. Ở đó **không có mật khẩu nào đăng nhập IMAP
được** — kể cả mật khẩu đúng. Đường còn lại là OAuth2 app-only: đăng ký một ứng
dụng, cho nó quyền đọc mailbox toàn tenant, rồi tool dùng token của ứng dụng đó
để đăng nhập thay từng mailbox. **Không cần thu mật khẩu của nhân viên khách
hàng** — thực tế đây mới là thứ làm việc migrate khả thi.

Khách hàng (admin của tenant nguồn) làm bốn bước:

1. **Entra ID → App registrations → New registration.** Ghi lại
   *Application (client) ID* và *Directory (tenant) ID*.
2. **API permissions → APIs my organization uses → Office 365 Exchange Online →
   Application permissions → `IMAP.AccessAsApp` → Add**, rồi bấm
   **Grant admin consent**.
3. **Certificates & secrets → New client secret.** Copy giá trị ngay, sau này
   không xem lại được.
4. Trong **Exchange Online PowerShell**, đăng ký service principal cho app đó:

   ```powershell
   New-ServicePrincipal -AppId <client-id> -ServiceId <object-id-cua-service-principal>
   ```

   Thiếu bước này thì token lấy về vẫn hợp lệ nhưng IMAP trả `AUTHENTICATE failed`
   — đây là chỗ hay tắc nhất.

Ngoài ra IMAP phải được bật cho từng mailbox:

```powershell
Set-CASMailbox -Identity user@contoso.com -ImapEnabled $true
```

Rồi khai vào `config.ini`:

```ini
[source]
provider = m365
auth = oauth2
oauth_tenant    = contoso.onmicrosoft.com
oauth_client_id = 00000000-0000-0000-0000-000000000000
oauth_client_secret_file = oauth-secret.txt
```

Để secret ra file riêng (`chmod 600`) thì `config.ini` vẫn còn backup/gửi đi
được. Cột `src_password` trong `users.csv` khi đó **để trống**.

`python3 mm.py doctor` sẽ thật sự gọi Microsoft xin token và in mã `AADSTS` nếu
bị từ chối — đó là cách nhanh nhất biết secret hết hạn hay thiếu consent.

> OAuth2 cần **imapsync 2.251 trở lên**. Tuỳ chọn `--oauthaccesstoken1` có
> từ 2.113, nhưng trước 2.251 imapsync vẫn đòi có `--password1` đi kèm nên
> không dùng một mình được. `doctor` kiểm tra và báo nếu bản đang cài quá cũ.
>
> Tool ghi token ra file rồi truyền đường dẫn file đó (không truyền token
> thẳng trên dòng lệnh). imapsync đọc lại file mỗi lần nó kết nối lại giữa
> chừng, nên trong suốt lần chạy tool giữ cho file đó luôn còn hạn — hộp thư
> chạy mười mấy tiếng cũng không đứt vì token hết hạn.

Tenant nào còn bật basic auth thì cứ để `auth = password` và điền mật khẩu như
bình thường.

Bật IMAP cho cả tenant một lượt, thay vì từng mailbox:

```powershell
Get-Mailbox -ResultSize Unlimited | Set-CASMailbox -ImapEnabled $true
```

### Microsoft 365: cái gì không đi qua IMAP

Tool này chuyển **mail**. Với một tenant Microsoft 365 thì "mail" ít hơn thứ
khách hàng hình dung khi họ nói *"chuyển hết Microsoft 365 sang"*. Đây là danh
sách để nói trước khi nhận việc — không phải để giải thích sau cutover.

**Đi qua được:** toàn bộ mail trong mailbox chính của user mailbox và shared
mailbox — cấu trúc folder lồng nhau, ngày tháng, trạng thái đã đọc, cờ, thư đã
trả lời. Shared mailbox chỉ là một dòng như mọi dòng khác trong `users.csv`,
miễn là đã bật IMAP cho nó.

**Không đi qua được:**

| Không lấy được | Vì sao |
|---|---|
| Calendar, Contacts, Tasks, Notes | Exchange không bày các folder này ra đường IMAP (khác Zimbra và IceWarp) |
| **Online Archive** (In-Place Archive) | Là một mailbox riêng, không có endpoint IMAP |
| Public folder | Không truy cập được bằng IMAP |
| Rule, chữ ký, out-of-office, category, quyền delegate | Nằm ở tầng Exchange, không ở tầng message |
| Recoverable Items (thùng rác cấp hai) | Không nhìn thấy qua IMAP |
| Room / Equipment mailbox | Chỉ có lịch, không có mail — `mkusers` tự bỏ qua |
| Microsoft 365 Group, Team site mailbox | IMAP không vào được |
| OneDrive, SharePoint, Teams | Khác hệ hoàn toàn |

**Online Archive là cái hay bị quên nhất**, vì nó không hiện ra ở bất kỳ bước
nào của tool: mailbox archive không nằm trên đường IMAP nên `discover` cũng
không thấy. Đếm xem có bao nhiêu mailbox bị ảnh hưởng *trước* khi chạy:

```powershell
Get-Mailbox -ResultSize Unlimited | Where-Object { $_.ArchiveStatus -eq "Active" } | Select-Object PrimarySmtpAddress, ArchiveStatus
```

Cách xử lý là kéo nội dung archive về hộp thư chính trước khi sync (nếu quota
bên đích đủ chỗ) — sau đó nó là mail bình thường và đi theo lần sync như mọi
folder khác. Nếu không kéo về được thì phải export riêng bằng Outlook hoặc
Graph API, và nói rõ với khách rằng phần đó nằm ngoài lần migrate này.

Nếu để `mkusers` sinh `users.csv` từ output `Get-Mailbox` (xem
[Cấu hình](#cấu-hình)) thì cột `ArchiveStatus` được đọc luôn và số mailbox có
archive được in ra ngay lúc đó.

### cPanel / DirectAdmin / Plesk (Dovecot), Courier

Hosting kiểu Maildir++ để mọi folder dưới tiền tố `INBOX.` với dấu phân cách là
`.`. Tool đọc lệnh `NAMESPACE` của **cả hai đầu**: tiền tố bên nguồn bị cắt đi,
tiền tố bên đích được thêm vào, và dấu phân cách được đổi theo. Không làm thế
thì hoặc hộp thư mới mọc ra một folder `INBOX` chứa tất cả, hoặc mọi folder bị
kéo ra ngoài INBOX.

Đây là việc **không thể phó mặc cho imapsync**: nó chỉ tự đổi tiền tố và dấu
phân cách cho những folder nó tự suy ra tên. Tên nào đi qua `--f1f2` thì nó lấy
nguyên văn (`sub imap2_folder_name` trả về trước khi gọi
`prefix_seperator_invertion`) — mà tool này ánh xạ tường minh gần như mọi folder.

Muốn ghi đè thì đặt `prefix` trong `[source]` hoặc `[dest]`: `auto` (mặc định),
`none`, hoặc một tiền tố viết cứng như `INBOX.` cho server trả về `NAMESPACE` sai.

Cái chặn thường gặp là `mail_max_userip_connections` của Dovecot (mặc định 10):
vượt là server từ chối kết nối mới. Giảm `workers` hoặc nâng giới hạn đó.

Courier không quảng bá SPECIAL-USE, nên folder đặc biệt được nhận ra **theo
tên**. Chạy `discover` kiểm lại trước khi sync thật.

### Zimbra

Bật IMAP trong COS (`zimbraImapEnabled = TRUE`). Zimbra bày cả `Contacts`,
`Emailed Contacts`, `Calendar`, `Tasks`, `Chats`, `Briefcase` ra đường IMAP —
tool tự bỏ qua chúng.

### Yahoo / Zoho / iCloud

Đều bắt buộc app-specific password, tạo trong phần bảo mật của account. Zoho còn
phải bật IMAP trong **Settings → Mail Accounts → IMAP Access**, và account ở
châu Âu dùng `imap.zoho.eu`.

### Nguồn không có trong danh sách

```ini
[source]
provider = imap
host = mail.khachhang.vn
```

Tool vẫn đọc cờ SPECIAL-USE và đối chiếu bảng tên tiếng Anh + tiếng Việt. Chạy
`discover` để xem nó phân loại đúng chưa trước khi chạy thật.

### Đăng nhập bằng tài khoản quản trị (`auth = master`)

Cách mặc định là xin mật khẩu của **từng hộp thư** rồi điền vào `users.csv`. Với
một cuộc migrate 200 mailbox thì đó là 200 lần đi hỏi, và mỗi mật khẩu thu về
đều là một thứ phải giữ rồi phải xoá. Nếu bạn làm chủ server — đầu nguồn tự
dựng, hoặc đầu đích là hệ thống của chính bạn — thì đi đường này thay thế:

```ini
[source]
provider = dovecot
host     = mail.congty-cu.vn
auth     = master

master_user          = migrate
master_password_file = master-pass.txt
```

Cột mật khẩu tương ứng trong `users.csv` (`src_password` cho nguồn,
`dst_password` cho đích) khi đó **để trống** — tool không đọc tới nữa.

Hỗ trợ với `provider` là `dovecot`, `zimbra`, hoặc `imap`. Đặt cho đầu nào cũng
được, và đặt cho **cả hai** đầu cũng được.

**Đã kiểm chứng tới đâu.** Nói thẳng để bạn biết chỗ nào đứng vững, chỗ nào nên
thử trước:

| | Trạng thái |
|---|---|
| **Dovecot** | Chạy thật đầu-cuối, cả hai `master_style`, cả hai đầu — Ubuntu 24.04 / Dovecot 2.3.19.1 / imapsync 2.314. Dựng lại bằng [`testrig/`](testrig/) |
| **Zimbra** | **Chưa chạy thật lần nào.** Phần dưới là suy ra từ tài liệu Zimbra và imapsync, không phải từ quan sát |
| **IMAP chung** | Để ngỏ, không phải lời hứa — tuỳ server |
| Kết nối TLS | Rig mặc định chạy 993 có đối chiếu chứng chỉ, và `auth = master` chạy trọn trên đó — preflight, sync, `verify` lệch 0 ngày. Gỡ CA khỏi trust store thì **cả hai** nửa dừng lại, đúng như phải thế |
| Kiểm tên host trong chứng chỉ | Rig không trả lời được (chứng chỉ của nó cấp đúng tên), nên có phép thử riêng: [`testrig/tlsprobe.sh`](testrig/tlsprobe.sh), 10/10 ô khớp trên VPS thật và trên máy dev |

Với Zimbra hoặc một server lạ, chạy `preflight` trên **một** hộp thư trước đã.

**Hai kiểu gửi tài khoản quản trị lên server.** Khác nhau ở giao thức chứ không
phải ở sở thích, nên chọn theo cái server chấp nhận:

| `master_style` | Cách hoạt động | Dùng khi |
|---|---|---|
| `authzid` (mặc định) | SASL PLAIN mang ba trường: hộp thư cần mở, tài khoản quản trị, mật khẩu quản trị (RFC 4616) | Dovecot có passdb `master = yes`; Zimbra với tài khoản admin (chưa kiểm chứng) |
| `separator` | Ghép thành một tên đăng nhập `hopthu*quantri` rồi LOGIN như thường | Dovecot có bật `auth_master_user_separator`, hoặc server không cho SASL PLAIN |

Đổi dấu phân cách bằng `master_separator` nếu server bạn không dùng `*`.

**Phía Dovecot** cần thêm một passdb quản trị vào
`/etc/dovecot/conf.d/10-auth.conf` rồi reload:

```
passdb {
  driver = passwd-file
  args = /etc/dovecot/master-users
  master = yes
}
```

Đúng bốn dòng đó là đủ trên Dovecot 2.3.19 — đã chạy thật. Vài bản khác cần
thêm `result_success = continue` trong khối này; nếu `doveadm auth login` không
qua thì đó là dòng đầu tiên nên thử.

File `/etc/dovecot/master-users` chứa dòng `migrate:{SHA512-CRYPT}$6$...` —
sinh hash bằng `doveadm pw -s SHA512-CRYPT`. Tên tài khoản quản trị thường là
tên trần (`migrate`), **không** phải `user@domain`.

Kiểm bằng **hai** lệnh trước khi động tới tool, đừng bỏ lệnh thứ hai:

```bash
doveadm auth login 'an@congty-cu.vn*migrate' 'MatKhauMaster'   # passdb
doveadm user an@congty-cu.vn                                    # userdb
```

`doveadm auth login` chỉ kiểm passdb. userdb hỏng thì nó vẫn báo
`auth succeeded`, trong khi mọi lần đăng nhập IMAP thật đều chết với
`[UNAVAILABLE] Internal error occurred` — một câu không hề nhắc tới userdb.

**Phía Zimbra** — *chưa kiểm chứng, xem bảng ở trên.* Theo tài liệu thì không
phải đổi cấu hình gì: đặt `master_user` là một tài khoản admin đầy đủ
(`admin@domain`) và giữ `master_style = authzid`. Chạy `preflight` trên một hộp
thư để biết chắc, và nếu nó không nhận thì `master_style = separator` là thứ
đáng thử tiếp.

> `master_password` là mật khẩu mở được **mọi** hộp thư trên server đó. Để nó ra
> file riêng bằng `master_password_file` rồi `chmod 600`, đừng để thẳng trong
> `config.ini` — file này hay bị copy đi copy lại giữa các cuộc migrate.

Chạy `preflight` trên **một** hộp thư trước khi tin cả danh sách: đây là chỗ
duy nhất biết chắc server có chấp nhận hay không.

## Chuẩn bị phía đích

```ini
[dest]
provider = icewarp
host = mail.congty.vn
```

`provider` bên đích quyết định bộ gợi ý xử lý lỗi khi ghi mail vào, và tên
folder dự phòng cho trường hợp server đích không gắn cờ SPECIAL-USE (IceWarp gọi
folder rác là `Spam`, Exchange gọi là `Junk Email`, Dovecot gọi là `Junk`).

**Tên folder đặc biệt bên đích thì tool tự đọc, không đoán theo provider.** Nó
đăng nhập đầu đích một lần rồi lấy cờ `\Sent` `\Drafts` `\Trash` `\Junk`
`\Archive` của chính server đó — đúng cách nó vẫn làm với đầu nguồn. Nhờ vậy
Gmail → Gmail ra `[Gmail]/Sent Mail`, Dovecot tiếng Việt ra `Thư đã gửi`, và
không ai phải gõ tay. Thứ tự ưu tiên:

1. Tên viết hẳn trong `[sync]` của `config.ini` — bạn gõ ra thì bạn thắng.
2. Tên thật đọc được bên đích qua cờ SPECIAL-USE.
3. Tên mặc định của provider đích — chỉ còn dùng khi server đích không gắn cờ
   nào. `discover --dest` sẽ cảnh báo khi rơi vào nước này.

- Tạo sẵn toàn bộ tài khoản đích trước khi chạy.
- Đặt quota đủ lớn. Ước lượng bằng dung lượng bên nguồn, cộng thêm ~20% dự phòng.
- Kiểm tra giới hạn kích thước mail của server đích. Nếu nguồn có mail lớn hơn
  giới hạn đó, đặt `maxsize` trong `config.ini` để bỏ qua chúng — nếu không
  imapsync sẽ báo lỗi từng cái một cho tới khi chạm `errorsmax` và dừng cả mailbox.
- Mở port 993 từ IP của VPS.
- Server đích để folder dưới tiền tố Maildir++ (`INBOX.`) thì tool tự dò và tự
  thêm vào — không phải khai gì. `discover` in ra tiền tố nó thấy được.

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
an.nguyen@congty-cu.com,abcd efgh ijkl mnop,an.nguyen@congty.vn,MatKhauDich1
```

Đầu nào chạy `auth = oauth2` hay `auth = master` thì cột mật khẩu tương ứng để
trống — không ai có mật khẩu của từng user, và tool cũng không cần.

`config.ini` — ít nhất phải sửa `[source] provider` và `[dest] host`. Mọi tuỳ
chọn đều có chú thích trong `config.example.ini`.

> `config.ini` và `users.csv` đã nằm trong `.gitignore`. Đừng commit chúng.

### TLS: mã hoá là một chuyện, xác thực là chuyện khác

`ssl = true` mở kết nối mã hoá. Nhưng mã hoá **không** trả lời được câu "mình
đang nói chuyện với đúng server đó chứ?" — trả lời câu đó là việc của chứng chỉ.

Tool đối chiếu chứng chỉ ở **cả hai** đường: kết nối IMAP của chính nó
(`preflight`, `discover`, `verify`) và kết nối của imapsync
(`--sslargs1 SSL_verify_mode=1`). Không khớp thì dừng, không chạy tiếp.

Và đối chiếu ở đây gồm **cả tên host**, không chỉ chuỗi chứng chỉ — chỗ này
đáng nói riêng, vì hai việc đó hay bị gộp làm một. Kẻ chen được vào đường
truyền thường có sẵn chứng chỉ thật, do CA công cộng ký, cấp cho tên miền của
chính nó: chỉ kiểm "chứng chỉ này có hợp lệ không" thì nó đi qua. Đã đo bằng
[`testrig/tlsprobe.sh`](testrig/tlsprobe.sh) — dựng một chứng chỉ do **đúng CA
đang tin** ký nhưng cấp cho tên khác, cả hai nửa đều từ chối:

```
imapsync --sslargs SSL_verify_mode=1    TỪ CHỐI: hostname verification failed
imaplib + create_default_context        TỪ CHỐI: CERTIFICATE_VERIFY_FAILED
cùng hai đường đó khi tls_verify = false   kết nối được  ← chính là lỗ hổng
```

Đây không phải mặc định của thư viện. `imaplib.IMAP4_SSL` khi không được truyền
context sẽ dùng `ssl._create_stdlib_context()` — `check_hostname = False`,
`verify_mode = CERT_NONE`, tức là **nhận bất kỳ chứng chỉ nào**. imapsync cũng
mặc định `SSL_verify_mode=0`. Cả hai đều phải được bảo mới kiểm.

Server dùng chứng chỉ tự ký hoặc hết hạn thì `preflight` sẽ báo
`certificate verify failed`. Ba cách xử lý, theo thứ tự nên ưu tiên:

1. Sửa `host` cho khớp tên trong chứng chỉ — hay gặp nhất là điền IP trong khi
   chứng chỉ cấp cho tên miền.
2. Thay hoặc gia hạn chứng chỉ bên server đó.
3. Nếu là hệ thống nội bộ và bạn chắc chắn đường truyền an toàn:

   ```ini
   tls_verify = false
   ```

   Đặt riêng cho từng đầu. Kết nối vẫn được mã hoá, chỉ thôi xác thực server.
   `doctor` sẽ nhắc mỗi lần chạy, cố ý.

> Cân nhắc kỹ trước khi tắt, nhất là khi đầu đó chạy `auth = master`: lúc ấy thứ
> đi qua đường truyền không còn là mật khẩu một hộp thư, mà là mật khẩu mở được
> **mọi** hộp thư trên server.

### Sinh `users.csv` từ danh sách mailbox của nguồn

Với tenant vài chục mailbox, gõ tay `users.csv` là chỗ dễ sai nhất trong cả
cuộc migrate: sai một ký tự trong địa chỉ thì mailbox đó **im lặng** không được
chuyển, và thường không ai phát hiện ra cho đến sau cutover. Danh sách đúng lấy
từ chính hệ thống nguồn — với Microsoft 365 / Exchange:

```powershell
Get-Mailbox -ResultSize Unlimited | Select-Object PrimarySmtpAddress,DisplayName,RecipientTypeDetails,ArchiveStatus | Export-Csv -NoTypeInformation -Encoding UTF8 mailboxes.csv
```

Rồi đưa file đó cho `mkusers`:

```bash
python3 mm.py mkusers mailboxes.csv --dst-domain congty.vn
```

```
Doc mailboxes.csv: 6 dong du lieu, cot dia chi 'PrimarySmtpAddress'

BO QUA 2 dong:
    - phonghop1@cu.com                     phong hop - chi co lich, khong co mail
    - DiscoverySearch@cu.onmicrosoft.com   hop thu he thong cua eDiscovery

LAY 3 mailbox:
    UserMailbox                    2
    SharedMailbox                  1

Dia chi ben dich (doi domain sang @congty.vn):
    an.nguyen@cu.com                       -> an.nguyen@congty.vn
    binh.tran@cu.com                       -> binh.tran@congty.vn
    ketoan@cu.com                          -> ketoan@congty.vn

CANH BAO: 1 mailbox co Online Archive (an.nguyen@cu.com). Archive la mailbox
          rieng, khong co duong IMAP nen tool KHONG chuyen duoc phan do --
          phai keo ve hop thu chinh truoc khi sync, hoac xuat rieng.

Da ghi 3 dong vao users.csv
```

Ba việc `mkusers` làm mà cắt/paste không làm được:

- **Bỏ loại mailbox không chứa mail** theo cột `RecipientTypeDetails`: phòng
  họp, thiết bị, hộp thư hệ thống (Discovery, Arbitration, Audit), Microsoft
  365 Group, public folder mailbox. Chỉ bỏ những loại **biết chắc** là không có
  mail — gặp loại lạ thì vẫn giữ và nói ra, vì bỏ nhầm một mailbox thật thì
  không ai thấy, còn giữ nhầm một mailbox rỗng thì `preflight` báo ngay.
- **Đếm mailbox có Online Archive** từ cột `ArchiveStatus`. Đây là lúc duy nhất
  con số đó xuất hiện trong cả quy trình — xem
  [phần trên](#microsoft-365-cái-gì-không-đi-qua-imap).
- **Đọc được file bất kể PowerShell ghi ra kiểu gì**: còn dòng `#TYPE` vì quên
  `-NoTypeInformation`, file UTF-16 của `Out-File` (đọc bằng UTF-8 không báo lỗi
  mà ra rác), dấu phân cách `;` của locale châu Âu, cột đặt tên khác
  (`EmailAddress`, `UserPrincipalName`), hoặc chỉ là danh sách địa chỉ trơ mỗi
  dòng một cái. Dùng `-` để đọc từ stdin.

Mật khẩu bên đích mặc định được **sinh ngẫu nhiên cho từng mailbox** (16 ký tự,
bỏ các ký tự dễ đọc lẫn như `0/O`, `1/l/I`) — tạo mailbox bên đích với đúng
những mật khẩu đó, hoặc đổi lại cột `dst_password` cho khớp.

| | |
|---|---|
| `--dst-domain congty.vn` | đổi domain bên đích; mặc định giữ nguyên địa chỉ nguồn |
| `--domain cu.com` | chỉ lấy mailbox thuộc domain này (tenant nhiều domain) |
| `--dst-password X` | dùng chung một mật khẩu cho mọi mailbox |
| `--blank-passwords` | để trống cột `dst_password`, điền tay sau |
| `--keep-all-types` | giữ cả phòng họp, thiết bị, hộp thư hệ thống |
| `--out duong/dan.csv` | ghi ra chỗ khác thay vì `users.csv` |
| `--force` | cho phép ghi đè file đã có |

`mkusers` **không ghi đè** `users.csv` nếu file đã tồn tại — file cũ thường
đang chứa mật khẩu thật. Muốn thay thế thì thêm `--force`.

Cột `src_password` luôn để trống: `Get-Mailbox` không cho ra mật khẩu của user.
Với nguồn chạy `auth = oauth2` hay `auth = master` thì như vậy là đủ; với nguồn
chạy `auth = password` thì phải điền cột đó tay trước khi `preflight`.

Đích chạy `auth = master` thì `mkusers` để trống luôn cột `dst_password` và bỏ
qua `--dst-password`: sinh mật khẩu ngẫu nhiên cho những hộp thư mà không chỗ
nào dùng tới chỉ tạo ra việc phải dọn.

---

## Chạy thử một mailbox trước

Đừng chạy cả danh sách ngay lần đầu. Cho đủ 20 dòng vào `users.csv`, rồi dùng
`--only` để chỉ đụng vào một hộp thư.

> Phần này và phần **Quy trình chạy** bên dưới lấy Gmail → IceWarp làm ví dụ cụ
> thể vì đó là cặp hay gặp nhất. Các bước y hệt nhau với mọi cặp nguồn/đích
> khác; chỗ nào ghi "Gmail" hay "IceWarp" thì thay bằng nhà cung cấp của bạn.

**Chọn hộp thư nào:** một hộp **nhỏ** (vài trăm MB, để vòng thử xong trong nửa
tiếng chứ không phải nửa ngày) và có đủ Sent, Drafts, vài label lồng nhau — như
vậy mới kiểm được phần đổi tên folder.

```bash
U=an.nguyen@congty-cu.com

python3 mm.py doctor                      # 1. môi trường
python3 mm.py preflight --only $U         # 2. đăng nhập được cả hai đầu
python3 mm.py discover  --only $U         # 3. folder bên nguồn + kế hoạch chuyển
python3 mm.py discover  --dest --only $U  # 4. folder thật bên đích
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

**Bước 5 cho biết khối lượng.** `--sizes` chạy `--justfoldersizes` của imapsync:
nó đọc kích thước từ metadata IMAP chứ không tải thân mail, nên tốn rất ít băng
thông. Kết quả gồm tổng dung lượng, mail lớn nhất, và trần trên số ngày:

```
Mailbox                                  Mail   Dung luong  Mail lon nhat  Ngay toi da
--------------------------------------------------------------------------------------
nhi.tran@namphonggroup.com             49.751      22.8 GB        40.7 MB           10
```

Chạy bước này cho **toàn bộ mailbox** ngay từ đầu để biết tổng khối lượng và
kiểm tra cột *Mail lớn nhất* có vượt giới hạn của server đích không.

> **Cột "Ngày tối đa" là trần trên, không phải dự báo.** Nó tính theo hạn mức
> 2500 MB/ngày Google công bố. Thực tế đã gặp account Workspace tải liền mạch
> **hơn 10 GB** mà không bị chặn — hộp 22,8 GB ở trên chạy xong trong khoảng một
> ngày chứ không phải 10 ngày. Muốn biết còn bao lâu thật sự thì xem tốc độ
> trong log lúc đang chạy:
>
> ```bash
> tail -1 logs/<mailbox>.sync.*.log
> ```
>
> Dòng đó có sẵn số mail/s và tổng đã chép. Lấy dung lượng còn lại chia cho tốc
> độ là ra.

> **Tốc độ do cả hai đầu quyết định, không riêng nguồn.** Đo thật với cùng một
> nguồn ra hai đích khác nhau: sang IceWarp **311,6 KiB/s**, sang Gmail
> **38,6 KiB/s** — chậm gấp 8 lần. Nghĩa là tốc độ ghi lại từ một cuộc migrate
> trước chỉ dùng lại được khi **cả hai** đầu giống nhau. Gmail làm đích thì cứ
> nhân thời gian dự tính lên, và lấy một hộp nhỏ đo trước rồi mới suy ra cả
> danh sách.

Sau bước 6, chạy lại `discover --dest` là thấy toàn bộ cây folder — đối chiếu
với kế hoạch ở bước 3 xem tên có đúng không, trước khi đụng vào mail thật.

**Bước 4 là bước dễ bỏ sót nhất.** Nó liệt kê folder có sẵn trên IceWarp, nói rõ
tên nào tool đọc được từ cờ SPECIAL-USE của server đích:

```
Doc theo co SPECIAL-USE ben IceWarp (khong can viet vao config.ini):
  junk_folder    = Junk E-mail
```

và chỉ cảnh báo khi còn tên không khớp thật:

```
CANH BAO: cac ten sau chua co ben IceWarp,
imapsync se TAO MOI folder trung ten:
  junk_folder    = Spam    (mac dinh cua provider, ben dich khong gan co)
```

Dòng đó nghĩa là server đích không khai folder rác bằng cờ, nên tool đang dùng
tên mặc định. Nếu cứ chạy, hộp thư sẽ có **hai folder rác song song** và bộ lọc
IceWarp vẫn dùng folder cũ. Viết tên thật vào `junk_folder` trong `config.ini`
rồi chạy tiếp.

**Tài khoản IceWarp mới tinh thường chỉ có `INBOX` và `Spam`.** IceWarp chỉ sinh
ra `Sent`/`Drafts`/`Trash` khi user đăng nhập và thực sự dùng. Nếu để imapsync
tạo trước, sau này IceWarp có thể tạo thêm bộ của nó với tên khác → hộp thư có
hai bộ folder. Cách chắc ăn: đăng nhập WebClient bằng tài khoản đó một lần, gửi
một mail thử, lưu một draft, xoá một mail — rồi chạy lại `discover --dest` để
xem tên thật IceWarp đặt, và sửa `config.ini` cho khớp.

### Nhiều folder nguồn đổ chung vào một folder đích

`discover` còn cảnh báo khi hai folder nguồn cùng ra một tên đích:

```
!! TRUNG TEN FOLDER DICH !!
  Drafts  <-  [Gmail]/Thư nháp, Drafts
```

Rất hay gặp với hộp thư **trước đây đã import từ nơi khác**: bên cạnh folder
chuẩn của nhà cung cấp hiện tại còn sót lại folder cũ cùng công dụng (`Drafts`,
`Sent Items`...). Cả hai sẽ trộn làm một bên đích.

Không mất mail, nhưng nên là quyết định có ý thức. Muốn giữ riêng thì đổi tên
label cũ trong `config.ini`:

```ini
extra_args = --regextrans2 s,^Drafts$,Drafts-cu,
```

Hoặc đổi tên đích của folder đặc biệt: `drafts_folder = Drafts-nguon`.

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

Đăng nhập IMAP cả hai đầu cho từng dòng trong CSV. Đây là bước bắt lỗi
sai mật khẩu, thiếu tài khoản, sai domain — rẻ và nhanh. Chạy nó trước.

### 3. `discover` — xem kế hoạch chuyển đổi

```bash
python3 mm.py discover
```

In ra folder nào bị **bỏ qua**, folder nào **đổi tên**, folder nào **giữ nguyên**,
cho từng mailbox. Đọc kỹ phần "BỎ QUA" — đó là những gì sẽ không sang bên đích.

Thêm `--dest` để xem folder có sẵn bên đích thay vì bên nguồn. Lệnh này cảnh
báo khi tên trong `config.ini` không khớp tên thật bên đích — nếu bỏ qua,
hộp thư sẽ có hai folder cùng công dụng nhưng khác tên.

### 4. `sync --dry` — chạy thử

```bash
python3 mm.py sync --dry
```

imapsync duyệt hết mọi thứ nhưng không ghi gì vào server đích. Xác nhận số lượng mail
khớp với mong đợi trước khi chạy thật.

### 5. `sync` — chạy thật

```bash
python3 mm.py sync
```

Chạy được, dừng được, chạy lại được. imapsync bỏ qua mail đã có bên đích nên
chạy lại **không** nhân đôi dữ liệu. Nếu đứt giữa chừng, chạy lại đúng lệnh đó.

**Ctrl-C dừng thật.** Màn hình hiện ngay `Dang dung... da bao N imapsync ket
thuc`, và tiến trình tắt trong khoảng một giây. Lý do phải nói rõ: một mình
Ctrl-C **không** đủ để dừng imapsync — ngoài Docker, imapsync hiểu `SIGINT` là
*"kết nối lại"* rồi chép tiếp, phải hai lần trong 2 giây nó mới thoát. Nên tool
tự hạ `SIGTERM` xuống thay vì ngồi đợi. Bấm lần nữa nếu muốn cắt phăng.

Dừng giữa chừng là chuyện an toàn, đã đo trên rig: cắt ở 312/606 mail rồi chạy
lại thì đúng 294 mail còn thiếu được chuyển, tổng khớp 606, **không mail nào
nhân đôi**, `verify` lệch 0 ngày. Mật khẩu tạm trong `state/` cũng được xoá
ngay cả khi bị cắt ngang.

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

Kết quả được ghi ra `logs/verify-<thời-điểm>.txt`, xả từng dòng nên `tail -f`
đọc được trong lúc đang chạy.

Bên nguồn lấy mẫu (đắt, có thể bị bóp băng thông), bên đích đọc **toàn bộ** folder
(rẻ, server nhà). Lấy mẫu cả hai đầu là sai: hai folder gần như không bao giờ
cùng số lượng và thứ tự cũng khác, nên hai mẫu rơi vào hai tập mail khác nhau
và phần không giao nhau bị báo nhầm là thiếu.

> Con số đếm đủ và đáng tin về việc có sót mail hay không nằm ở dòng
> `Messages found in host1 not in host2` cuối log sync — imapsync đối chiếu
> từng mail chứ không lấy mẫu. Cột **`thiếu bên đích`** ở đây chỉ là mẫu.

> Cột **`không kiểm được`** là mail bên nguồn vốn **không có `Message-Id`** —
> hay gặp ở Drafts (thư soạn dở chưa gửi bao giờ thì chưa ai gắn định danh cho
> nó) và ở mail do máy quét sinh ra. Chúng vẫn được chuyển bình thường, và
> `--addheader` gắn cho mỗi cái một định danh lúc chép sang nên chúng **không**
> bị nhân đôi ở vòng delta. Nhưng đúng vì thế mà hai đầu không còn chung
> `Message-Id` nào để ghép, nên phép đối chiếu ngày không với tới chúng. Muốn
> kiểm thì phải mở bằng mắt.
>
> Những mail này **không** rơi vào cột `thiếu bên đích`: thiếu `Message-Id` thì
> chúng bị loại khỏi bảng chỉ mục ngay từ đầu, tức là trước cả phép trừ sinh ra
> con số đó. Nếu không đếm riêng, chúng biến mất khỏi mọi con số và `verify`
> sẽ báo "khớp hết" trong khi im lặng bỏ qua một phần hộp thư.

### 7. Cutover

Ngày đổi MX, chạy vòng delta để nhặt mail mới về sau lần sync đầu:

```bash
python3 mm.py sync --since-days 7
```

Sau khi MX đã trỏ về IceWarp và đã ổn định, chạy thêm một lần nữa để nhặt nốt
mail đến muộn ở Gmail.

> **`--since-days` đếm theo ngày mail *về* hộp thư, không phải ngày trên header
> `Date:`.** Hai mốc này khác nhau, và đúng lúc cutover thì khoảng cách đó ăn
> mail thật: thư forward lại, thư kẹt hàng đợi vài ngày mới giao, thư từ hệ
> thống có đồng hồ sai, thư không có header `Date:` — tất cả đều **về** trong
> cửa sổ cutover nhưng mang `Date:` cũ.
>
> Mặc định của imapsync là lọc bằng `SEARCH SENTSINCE`, tức header `Date:`, nên
> nó bỏ lại đúng những thư đó — mà báo cáo vẫn `OK`, không một dòng cảnh báo.
> Đo trên rig: ba thư cùng vừa về, `--since-days 2` chỉ chuyển một. Tool thêm
> `--noabletosearch` để đổi sang `INTERNALDATE` cho khớp với `date_source =
> internal` mà nó đang giữ.
>
> Cái giá: imapsync phải `FETCH` ngày của từng thư thay vì để server `SEARCH`,
> nên vòng delta trên hộp thư rất lớn sẽ chậm hơn. Đổi lại là không mất thư ở
> đúng lúc không sửa lại được.
>
> Nếu đặt `date_source = header` thì tool **không** thêm cờ đó — lúc ấy chính
> `Date:` mới là mốc ta cố ý dùng, và cả hai đầu đều mang nó.

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

## Hạn mức của nguồn — cái này quyết định lịch chạy

Hai loại hạn mức hoàn toàn khác nhau, và nhầm chúng với nhau sẽ dẫn tới xử lý sai:

| Nguồn | Loại giới hạn | Gặp thì làm gì |
|---|---|---|
| Gmail / Workspace | **Dung lượng/ngày** — 2500 MB công bố cho mỗi account | Chờ reset (1–24h) rồi chạy lại |
| Microsoft 365 | **Throttling tức thời** — `Server Unavailable`, không có hạn mức ngày | Giảm `workers` xuống 2–3, chạy tiếp ngay |
| Dovecot / cPanel | **Số kết nối đồng thời** — `mail_max_userip_connections`, mặc định 10 | Giảm `workers` hoặc nâng giới hạn trên server |
| Zimbra, Courier, IMAP chung | Tuỳ cấu hình server | Xem log, giảm `workers` |

Chỉ Gmail mới có "còn bao nhiêu ngày nữa", nên cột **Ngày tối đa** của
`sync --sizes` chỉ xuất hiện khi nguồn là Gmail. Với nguồn khác, con số đó không
tồn tại và tool không bịa ra.

Phần còn lại của mục này nói riêng về Gmail.

Google **công bố** giới hạn 2500 MB/ngày cho mỗi account qua IMAP download.
Vượt thì account bị khoá IMAP, thường 1 giờ, có thể tới 24 giờ.

> **2500 MB là trần công bố, không phải trần thực tế.** Số liệu một đêm chạy
> thật trên Workspace (8 mailbox, 46,5 GB, 103.546 mail): hộp **14,6 GB chạy
> liền mạch 11h23m không hề bị chặn**, hộp 6,5 GB cũng vậy. Lấy 2500 MB ra tính
> lịch thì hộp đó phải mất 6 ngày — thực tế xong trong một đêm.

Hệ quả thực tế:

- **Không dự báo được hộp nào bị chặn bằng dung lượng.** Trong đêm nói trên, hộp
  kéo *nhiều byte nhất* (14,6 GB) về đích sạch, còn hộp bị cắt lại đứng sau nó
  về byte (13,8 GB) nhưng **nhiều mail nhất** — 48k mail được nhận diện. Thông
  báo của Google là `exceeded command or bandwidth limits`: nó đếm cả **số lệnh
  IMAP**, mà số lệnh tính theo mail *quét qua*, không phải mail *chuyển được*.
  Nên hộp nhiều mail nhỏ rủi ro hơn hộp ít mail nặng.
- **Bị chặn không phải là hỏng.** Chờ reset rồi chạy lại cùng lệnh `sync`; mail
  đã chuyển không bị chép lại. Hộp lớn thì lặp lại vài ngày cho đến khi hết.
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
- `Chạy tiếp` = `sync --resume`: bỏ qua mailbox đã chạy xong (có
  `state/<mailbox>/done.marker`). Dùng nó thay `Chạy thật` khi lần trước chỉ
  hỏng vài hộp, khỏi quét lại những hộp đã xong
- Log chạy trực tiếp, tự cuộn theo
- Form thêm mailbox, ghi thẳng vào `users.csv`; dấu ✕ ở cuối mỗi dòng để xoá
  khỏi danh sách (chỉ xoá dòng trong CSV — mail đã chuyển và log vẫn còn)

Ba nguyên tắc an toàn của giao diện này:

- **Mật khẩu không bao giờ được gửi ngược về trình duyệt.** API chỉ trả về một cờ
  cho biết ô đó đã có mật khẩu hay chưa.
- **Mỗi lúc chỉ một tác vụ.** Bấm nút thứ hai khi đang chạy sẽ bị từ chối, không
  có chuyện hai lệnh imapsync giẫm lên nhau.
- **Hai nút có ghi vào IceWarp — `Chạy thật` và `Chạy tiếp` — đều hỏi lại trước
  khi chạy**, và hộp thoại nói rõ đang áp dụng cho bao nhiêu mailbox. Các nút
  còn lại không ghi gì.

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
python3 mm.py report --all        # gộp tất cả: dòng mới nhất của từng mailbox
python3 mm.py report --list       # liệt kê các lần đã chạy
python3 mm.py report --all --out bao-cao.html
```

**Báo cáo cho sếp thì dùng `--all`.** Mỗi file run chỉ chứa những mailbox của
lần chạy đó. Chạy rải rác vài đêm — 8 hộp một đêm, rồi từng hộp lẻ chạy lại —
thì không file nào còn chứa đủ danh sách, và `report` không kèm `--all` sẽ ra
một bảng đúng nhưng chỉ có một dòng. Khi điều đó xảy ra, tool tự nhắc.

`--all` gộp một dòng cho mỗi mailbox, nhưng hai nhóm cột mang nghĩa khác nhau:

| Cột | Lấy từ đâu |
|---|---|
| Kết quả, Folder, Ghi chú | Lần chạy **mới nhất** — đó là trạng thái hiện tại |
| Mail, Dung lượng, Thời gian | **Cộng dồn** qua tất cả các lần chạy `sync` |

Phải cộng dồn vì mỗi dòng run chỉ mang thống kê của riêng lần chạy đó
(`Messages transferred` của imapsync). Một hộp thư bị Gmail cắt giữa chừng rồi
chạy lại đã chuyển mail ở cả hai lần — lấy lần cuối làm báo cáo là kể thiếu
công của chính mình. Trong một cuộc migrate thật, cách cũ báo 87.936 mail
trong khi thực tế đã chuyển gần 122.700.

Cộng dồn không sợ đếm trùng: imapsync bỏ qua mail đã có bên đích, nên lần chạy
sau chỉ đếm phần nó thật sự chép thêm. Lần chạy `--dry` không chép gì nên
không được cộng vào.

> Bảng trên **dashboard** vẫn hiện số của lần chạy gần nhất, không cộng dồn —
> nó là màn hình theo dõi vận hành, không phải báo cáo tổng kết. Đừng ngạc
> nhiên khi hai bên lệch nhau ở hộp thư đã chạy nhiều lần.

Mailbox lỗi sẽ kèm gợi ý xử lý cụ thể, không phải mã lỗi trần.

Gợi ý được **tính lại từ log** mỗi lần xem, không đọc từ file `runs/*.json`. Nhờ
vậy khi luật chẩn đoán được sửa, mọi báo cáo cũ tự đúng theo — kể cả báo cáo của
mailbox đã xong và sẽ không bao giờ chạy lại. Đổi lại: xoá `logs/` thì các lần
chạy cũ mất gợi ý (số liệu vẫn còn), và tool quay về dùng gợi ý đã lưu.

---

## Các lệnh khác

```bash
python3 mm.py providers                            # nguồn/đích được hỗ trợ
python3 mm.py providers dovecot                    # chi tiết một cái
python3 mm.py mkusers mailboxes.csv                # sinh users.csv từ Get-Mailbox
python3 mm.py sync --only an@cu.com,binh@cu.com   # chỉ vài mailbox
python3 mm.py sync --resume                        # bỏ qua mailbox đã xong
python3 mm.py sync --workers 5                     # ghi đè số luồng song song
python3 mm.py sync --since-days 3                  # chỉ mail mới hơn 3 ngày
```

`providers` chạy được cả khi chưa có `config.ini` — cần biết điền gì vào
`provider =` trước đã.

`--resume` dựa vào file đánh dấu trong `state/<user>/done.marker`. Muốn ép chạy
lại một mailbox thì xoá file đó đi.

---

## Xử lý sự cố

Tool tự dịch các lỗi hay gặp thành việc cần làm, **theo đúng nhà cung cấp đang
chạy** — báo "dùng App Password của Google" cho một ca migrate từ Zimbra không
chỉ vô dụng, nó làm người trực đi sai hướng đúng lúc đang gặp sự cố. Bảng dưới
là để tra nhanh:

Chung cho mọi nguồn:

| Triệu chứng | Nguyên nhân |
|---|---|
| `[OVERQUOTA]` lúc ghi sang đích | Hộp thư đích đầy |
| `Message too big` | Vượt giới hạn kích thước của server đích; đặt `maxsize` |
| `[TRYCREATE]` | Không tạo được folder bên đích — với IceWarp thường do trùng tên với folder PIM (Contacts, Calendar, Tasks, Notes) |
| `certificate verify failed` | Chứng chỉ TLS hết hạn, tự ký, hoặc không khớp `host` trong `config.ini` — sửa cho khớp, hoặc `tls_verify = false` nếu chắc chắn đường truyền an toàn |
| `Can't locate ...pm in @INC` | Thiếu module Perl; chạy lại `install.sh` hoặc `cpanm <Module>` |
| `Unknown option` | imapsync quá cũ so với tuỳ chọn tool dùng; chạy `doctor` |
| `imapsync bị hạ bởi SIGPIPE (tín hiệu 13)` | Một trong hai server biến mất **giữa lúc đang chép** — reboot, quá tải, đứt mạng, firewall cắt phiên đang mở. Không phải lỗi đăng nhập. Kiểm hai đầu còn sống không rồi chạy lại đúng lệnh đó |
| `imapsync bị hạ bởi SIGKILL (tín hiệu 9)` | Bị giết thẳng, hay gặp nhất là OOM killer khi VPS hết RAM — xem `dmesg -T \| tail`. Giảm `workers` rồi chạy lại |

> Khi imapsync bị một tín hiệu hạ, nó **không kịp in khối thống kê** ở cuối. Lúc
> đó cột `Mail` trong báo cáo được đếm lại từ chính những dòng `copied to` mà nó
> đã in — số đó là mail đã sang thật, không phải ước lượng. Chạy lại đúng lệnh
> cũ để chuyển nốt phần còn thiếu; mail đã chép không bị chép lại.

Gmail:

| Triệu chứng | Nguyên nhân |
|---|---|
| `Invalid credentials` | Đang dùng mật khẩu thường thay vì App Password |
| `Application-specific password required` | Account bật 2FA, phải dùng App Password |
| `Web login required` | Google chặn; đăng nhập Gmail bằng trình duyệt một lần rồi thử lại |
| `Bandwidth limit` / `[LIMIT]` | Vượt hạn mức IMAP; chờ reset rồi chạy lại |
| `Too many simultaneous connections` | Quá 15 kết nối trên một account; giảm `workers` |
| `[OVERQUOTA]` kèm `could not be fetched` | Là hạn mức **Gmail**, không phải server đích — xem mục hạn mức ở trên |
| `could not be fetched: ... BAD Unknown command <id>` | **Phiên đọc chết giữa chừng, mail không hỏng.** Dấu hiệu: lỗi nằm liên tiếp trên những mail sát nhau, và cùng một mã phiên lặp ở mọi dòng `Err ...`. Chạy lại đúng lệnh đó; mail đã chép sang không bị chép lại. Hay gặp sau vài nghìn mail liên tục — giảm `workers`, đặt `maxbytespersecond` cho phiên sống lâu hơn |

> Đừng lẫn hai kiểu `could not be fetched`. Có `BAD` trong câu là **phiên**
> hỏng → chạy lại. Không có `BAD`, chỉ literal `{0}` rỗng rải rác → **mail**
> hỏng sẵn ở nguồn, chạy lại bao nhiêu lần cũng vậy: xử lý tay từng cái rồi
> `touch state/<mailbox>/done.marker`. Hai việc ngược nhau, đoán nhầm thì hoặc
> vứt mail còn đọc được, hoặc chạy lại mãi một mail hỏng.

Microsoft 365:

| Triệu chứng | Nguyên nhân |
|---|---|
| `basic authentication is disabled` | Tenant đã tắt basic auth; chuyển sang `auth = oauth2` |
| `AADSTS7000215` | Client secret sai hoặc đã hết hạn |
| `AADSTS700016` | Client ID không tồn tại trong tenant đó |
| `AADSTS900023` | Sai `oauth_tenant` |
| `AUTHENTICATE failed` dù token lấy được | Chưa chạy `New-ServicePrincipal`, hoặc chưa admin consent `IMAP.AccessAsApp` |
| `IMAP4 protocol is disabled` | Chưa `Set-CASMailbox -ImapEnabled $true` cho mailbox đó |
| `Server Unavailable` | Throttling — giảm `workers`, **không phải** hạn mức ngày, không cần chờ |

`auth = master`:

| Triệu chứng | Nguyên nhân |
|---|---|
| `Unsupported authentication mechanism` | Server không nhận SASL PLAIN; đổi `master_style = separator` |
| `Plaintext authentication disallowed` | Kết nối chưa mã hoá; đặt `ssl = true` và `port = 993` |
| `Authorization failed` / `not authorized to login as` | Đăng nhập được nhưng không được mở hộp thư đó: sai quyền, hộp thư đích chưa tạo, hoặc passdb Dovecot thiếu `master = yes` |
| `Authentication failed` ngay từ hộp thư đầu tiên | Sai `master_user` / `master_password`, hoặc Dovecot chưa reload sau khi thêm passdb |

Dovecot / cPanel / Courier / Zimbra:

| Triệu chứng | Nguyên nhân |
|---|---|
| `Maximum number of connections ... exceeded` | `mail_max_userip_connections`; giảm `workers` hoặc nâng giới hạn |
| `Invalid credentials` | Một số hosting dùng tên đăng nhập dạng `user_domain` chứ không phải `user@domain` |
| Folder bên đích mọc ra một cây `INBOX` lồng nhau, hoặc nằm ngoài INBOX | Tiền tố namespace dò sai; đặt `prefix` tường minh trong `[source]`/`[dest]` |

Nếu cần đào sâu, xem file log của mailbox đó — nó chứa nguyên văn output imapsync.
Muốn chi tiết hơn nữa, thêm vào `config.ini`:

```ini
extra_args = --debugimap
```

### Folder bị đặt tên lạ bên đích

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
  providers.py             hồ sơ từng nhà cung cấp: folder, hạn mức, chuẩn bị
  oauth.py                 lấy và làm mới OAuth2 token của Microsoft
  config.py                đọc config.ini
  users.py                 đọc users.csv, chuẩn hoá app password
  mailboxes.py             đọc danh sách mailbox của nguồn -> sinh users.csv
  discover.py              đọc folder bên nguồn, dựng kế hoạch chuyển đổi
  imaputf7.py              giải mã tên folder để hiển thị
  runner.py                dựng và chạy lệnh imapsync, đọc kết quả
  hints.py                 dịch lỗi imapsync thành việc cần làm
  verify.py                đối chiếu ngày tháng giữa hai đầu
  report.py                bảng terminal, CSV, HTML
  cli.py                   các lệnh con
  web.py                   dashboard: HTTP server, chạy job
  web_ui.py                trang HTML của dashboard
tests/                     502 test, không chạm mạng
testrig/                   hai Dovecot để thử những gì test không chứng minh được
install.sh                 cài imapsync + module Perl
.github/workflows/         CI: chạy bộ test trên Python 3.8 / 3.10 / 3.12
```

**Thêm một nguồn mới** là thêm một `Provider` vào `providers.py` — khai báo host
mặc định, bảng tên folder, folder cần bỏ qua, hạn mức, và các bước chuẩn bị.
Không phải sửa logic ở chỗ nào khác. `tests/test_providers.py` có một test dựng
provider ngay trong test để chứng minh điều đó.

Chạy test:

```bash
python3 -m unittest discover -s tests
```

Test dùng một imapsync giả và dữ liệu folder mẫu, nên chạy được ở bất cứ đâu,
không cần mạng và không cần tài khoản thật.

CI chạy đúng lệnh đó trên mỗi push và pull request, với Python **3.8** (bản cũ
nhất còn gặp trên VPS khách), **3.10** và **3.12** (bản của Ubuntu 24.04, nơi
tool đã chạy thật) — xem [`.github/workflows/tests.yml`](.github/workflows/tests.yml).
Không có bước cài đặt nào vì bộ test chỉ dùng thư viện chuẩn.

---

## Ghi chú

- imapsync là phần mềm tự do (giấy phép NOLIMIT); tác giả có bán bản build sẵn
  và dịch vụ hỗ trợ. `install.sh` lấy mã nguồn từ repo GitHub chính thức.
- Tool này chỉ chuyển **mail**. Lịch, danh bạ, task không đi qua IMAP — phải
  export/import riêng. Với Zimbra thì các folder đó *có* hiện trên IMAP nhưng
  nội dung không dùng được bên đích, nên tool bỏ qua chúng. Danh sách đầy đủ
  những gì **không** đi qua được với một tenant Microsoft 365 nằm ở
  [phần này](#microsoft-365-cái-gì-không-đi-qua-imap).
- Bộ lọc, chữ ký, chuyển tiếp bên nguồn cũng không được chuyển; phải tạo lại
  thủ công trên server đích.
- `auth = master` nhận `dovecot`, `zimbra` và `imap` — xem
  [phần này](#đăng-nhập-bằng-tài-khoản-quản-trị-auth--master). Mới chỉ **Dovecot**
  là đã chạy thật; Zimbra suy từ tài liệu, chưa kiểm chứng. Provider khác đặt
  giá trị đó sẽ báo lỗi ngay lúc đọc config chứ không hỏng giữa chừng.
