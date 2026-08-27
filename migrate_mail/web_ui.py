# -*- coding: utf-8 -*-
"""Trang HTML cua dashboard. Tu chua tat ca, khong tai gi tu ben ngoai."""

PAGE = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>migrate-mail</title>
<style>
 :root{
   --bg:#f6f7f9; --panel:#fff; --ink:#16191d; --muted:#6b7280; --line:#e3e6ea;
   --accent:#2563eb; --ok:#137333; --err:#c5221f; --warn:#a16207; --warnbg:#fffbe6;
   --code:#0f172a; --codeink:#d7dde8;
 }
 @media (prefers-color-scheme:dark){
   :root{
     --bg:#0f1216; --panel:#171b21; --ink:#e6e9ee; --muted:#98a2b3; --line:#262c35;
     --accent:#60a5fa; --ok:#4ade80; --err:#f87171; --warn:#fbbf24; --warnbg:#2a2410;
     --code:#0b0e12; --codeink:#c8d2e0;
   }
 }
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--ink);
      font:14px/1.5 system-ui,"Segoe UI",Roboto,Arial,sans-serif}
 header{background:var(--panel);border-bottom:1px solid var(--line);
        padding:.85rem 1.25rem;display:flex;gap:1.25rem;align-items:baseline;flex-wrap:wrap}
 header h1{font-size:1rem;margin:0;font-weight:650;letter-spacing:-.01em}
 header .route{color:var(--muted);font-size:13px}
 header .route b{color:var(--ink);font-weight:600}
 main{padding:1.25rem;max-width:1400px;margin:0 auto;display:grid;gap:1.25rem}
 .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
 .card > h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;
            color:var(--muted);margin:0;padding:.7rem 1rem;border-bottom:1px solid var(--line)}
 .pad{padding:1rem}
 .bar{display:flex;gap:.45rem;flex-wrap:wrap;align-items:center;padding:1rem;
      border-bottom:1px solid var(--line)}
 button{font:inherit;padding:.42rem .8rem;border-radius:7px;border:1px solid var(--line);
        background:var(--bg);color:var(--ink);cursor:pointer}
 button:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
 button:disabled{opacity:.45;cursor:not-allowed}
 button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
 button.primary:hover:not(:disabled){filter:brightness(1.08);color:#fff}
 button.danger{border-color:var(--err);color:var(--err)}
 .sep{width:1px;height:22px;background:var(--line);margin:0 .35rem}
 .scope{color:var(--muted);font-size:13px;margin-left:auto}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{padding:.5rem .7rem;text-align:left;border-bottom:1px solid var(--line);
       vertical-align:top}
 th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;
    letter-spacing:.04em;white-space:nowrap}
 tbody tr:last-child td{border-bottom:none}
 tbody tr:hover{background:color-mix(in srgb,var(--accent) 6%,transparent)}
 td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
 .badge{display:inline-block;padding:.1rem .45rem;border-radius:999px;font-size:11.5px;
        font-weight:600;border:1px solid transparent;white-space:nowrap}
 .b-ok{color:var(--ok);border-color:var(--ok)}
 .b-err{color:var(--err);border-color:var(--err)}
 .b-idle{color:var(--muted);border-color:var(--line)}
 .tip{margin-top:.3rem;padding:.3rem .5rem;background:var(--warnbg);
      border-left:3px solid var(--warn);font-size:12px;border-radius:0 4px 4px 0}
 pre{margin:0;padding:1rem;background:var(--code);color:var(--codeink);
     font:12.5px/1.55 ui-monospace,"SFMono-Regular",Consolas,monospace;
     overflow:auto;max-height:26rem;white-space:pre-wrap;word-break:break-word}
 .job{display:flex;gap:.7rem;align-items:center;padding:.7rem 1rem;
      border-bottom:1px solid var(--line);flex-wrap:wrap}
 .dot{width:9px;height:9px;border-radius:50%;background:var(--muted);flex:none}
 .dot.run{background:var(--accent);animation:pulse 1.1s ease-in-out infinite}
 .dot.ok{background:var(--ok)} .dot.err{background:var(--err)}
 @keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
 form.add{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
          gap:.6rem;padding:1rem;align-items:end}
 label{display:block;font-size:12px;color:var(--muted);margin-bottom:.25rem}
 input{font:inherit;width:100%;padding:.42rem .6rem;border-radius:7px;
       border:1px solid var(--line);background:var(--bg);color:var(--ink)}
 input:focus{outline:2px solid color-mix(in srgb,var(--accent) 45%,transparent);
             outline-offset:1px;border-color:var(--accent)}
 .note{color:var(--muted);font-size:12.5px;padding:0 1rem 1rem}
 .err{color:var(--err)}
 .empty{padding:2rem 1rem;text-align:center;color:var(--muted)}
 button.rm{padding:.1rem .4rem;font-size:12px;line-height:1.3;color:var(--muted);
           border-color:transparent;background:transparent}
 button.rm:hover:not(:disabled){color:var(--err);border-color:var(--err)}
 td.act{text-align:right;white-space:nowrap}
</style>
</head>
<body>
<header>
  <h1>migrate-mail</h1>
  <div class="route">
    <b id="src">…</b> &rarr; <b id="dst">…</b>
  </div>
  <div class="route" id="meta"></div>
</header>

<main>
  <section class="card">
    <div class="bar">
      <button data-act="preflight">Kiểm tra đăng nhập</button>
      <button data-act="discover">Kế hoạch folder</button>
      <button data-act="dest">Folder bên IceWarp</button>
      <button data-act="sizes">Đo dung lượng</button>
      <span class="sep"></span>
      <button data-act="folders">Tạo cây folder</button>
      <button data-act="dry">Chạy khan</button>
      <button data-act="sync" class="primary">Chạy thật</button>
      <span class="sep"></span>
      <button data-act="verify">Đối chiếu ngày</button>
      <span class="scope" id="scope"></span>
    </div>
    <table>
      <thead><tr>
        <th style="width:28px"><input type="checkbox" id="all" title="Chọn tất cả"></th>
        <th>Nguồn</th><th>Đích</th><th>Kết quả</th>
        <th class="num">Folder</th><th class="num">Mail</th>
        <th class="num">Dung lượng</th><th class="num">Thời gian</th>
        <th>Ghi chú</th><th></th>
      </tr></thead>
      <tbody id="rows"><tr><td colspan="10" class="empty">Đang tải…</td></tr></tbody>
    </table>
  </section>

  <section class="card">
    <div class="job">
      <span class="dot" id="dot"></span>
      <b id="jobname">Chưa chạy tác vụ nào</b>
      <span class="route" id="jobinfo"></span>
    </div>
    <pre id="log">Kết quả sẽ hiện ở đây.</pre>
  </section>

  <section class="card">
    <h2>Thêm mailbox</h2>
    <form class="add" id="addform" autocomplete="off">
      <div><label>Địa chỉ Gmail</label>
           <input name="src_user" placeholder="an@congty-cu.com" required></div>
      <div><label>App Password (16 ký tự)</label>
           <input name="src_password" type="password" required></div>
      <div><label>Địa chỉ IceWarp</label>
           <input name="dst_user" placeholder="an@congty.vn" required></div>
      <div><label>Mật khẩu IceWarp</label>
           <input name="dst_password" type="password" required></div>
      <div><button type="submit" class="primary">Thêm vào danh sách</button></div>
    </form>
    <div class="note" id="addnote">
      Ghi thẳng vào <code id="usersfile">users.csv</code> trên máy chủ này.
      Mật khẩu không bao giờ được gửi ngược về trình duyệt.
      Muốn sửa một dòng thì xoá bằng dấu ✕ ở cuối dòng rồi thêm lại.
    </div>
  </section>
</main>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
  (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

let state = null, selected = new Set(), timer = null, stick = true;

function scope() {
  return selected.size ? Array.from(selected) : [];
}

function renderScope() {
  const n = selected.size;
  $("scope").textContent = n
    ? n + " mailbox được chọn"
    : (state && state.mailboxes.length
        ? "Áp dụng cho tất cả " + state.mailboxes.length + " mailbox"
        : "");
}

function badge(m) {
  if (m.ket_qua === "OK")  return '<span class="badge b-ok">OK</span>';
  if (m.ket_qua === "LOI") return '<span class="badge b-err">LỖI</span>';
  return '<span class="badge b-idle">chưa chạy</span>';
}

function renderRows() {
  const box = $("rows");
  if (!state.mailboxes.length) {
    box.innerHTML = '<tr><td colspan="10" class="empty">' +
      'Chưa có mailbox nào. Thêm ở khung bên dưới.</td></tr>';
    return;
  }
  box.innerHTML = state.mailboxes.map((m) => {
    const tips = (m.goi_y || []).map((t) =>
      '<div class="tip">' + esc(t) + "</div>").join("");
    const warn = (!m.has_src_password || !m.has_dst_password)
      ? '<div class="tip">Thiếu mật khẩu trong users.csv</div>' : "";
    return '<tr><td><input type="checkbox" data-u="' + esc(m.src_user) + '"' +
      (selected.has(m.src_user) ? " checked" : "") + "></td>" +
      "<td>" + esc(m.src_user) + (m.done ? ' <span class="badge b-ok">đã xong</span>' : "") + "</td>" +
      "<td>" + esc(m.dst_user) + "</td>" +
      "<td>" + badge(m) + "</td>" +
      '<td class="num">' + esc(m.folder) + "</td>" +
      '<td class="num">' + esc(m.mail) + "</td>" +
      '<td class="num">' + esc(m.dung_luong) + "</td>" +
      '<td class="num">' + esc(m.thoi_gian) + "</td>" +
      "<td>" + esc(m.ghi_chu) + tips + warn + "</td>" +
      '<td class="act"><button class="rm" data-rm="' + esc(m.src_user) +
      '" title="Xoá khỏi danh sách">✕</button></td></tr>';
  }).join("");

  box.querySelectorAll("input[data-u]").forEach((cb) => {
    cb.onchange = () => {
      cb.checked ? selected.add(cb.dataset.u) : selected.delete(cb.dataset.u);
      renderScope();
    };
  });

  box.querySelectorAll("button[data-rm]").forEach((btn) => {
    btn.disabled = !!(state.job && state.job.running);
    btn.onclick = () => removeUser(btn.dataset.rm);
  });
}

function renderJob() {
  const j = state.job, dot = $("dot"), log = $("log");
  dot.className = "dot";
  if (!j) {
    $("jobname").textContent = "Chưa chạy tác vụ nào";
    $("jobinfo").textContent = "";
    return;
  }
  const secs = Math.round(j.elapsed);
  const time = secs >= 60 ? Math.floor(secs / 60) + "m" + ("0" + (secs % 60)).slice(-2) + "s"
                          : secs + "s";
  if (j.running)      { dot.classList.add("run"); }
  else if (j.error || (j.exit_code !== null && j.exit_code !== 0)) { dot.classList.add("err"); }
  else                { dot.classList.add("ok"); }

  $("jobname").textContent = j.action_label + (j.running ? " — đang chạy" : " — xong");
  const who = j.only.length ? j.only.join(", ") : "tất cả mailbox";
  $("jobinfo").textContent = who + " · " + time +
    (j.running || j.exit_code === null ? "" : " · mã thoát " + j.exit_code);

  const text = (j.lines || []).join("\n") || "(chưa có output)";
  if (log.textContent !== text) {
    const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
    log.textContent = text;
    if (stick && atEnd) log.scrollTop = log.scrollHeight;
  }
  document.querySelectorAll("button[data-act]").forEach((b) => { b.disabled = j.running; });
}

async function removeUser(user) {
  const msg = "Xoá " + user + " khỏi danh sách?\n\n" +
    "Chỉ xoá dòng trong users.csv. Mail đã chuyển sang IceWarp và log vẫn còn nguyên.";
  if (!confirm(msg)) return;
  try {
    const res = await fetch("/api/users/remove", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ src_user: user }),
    });
    const data = await res.json();
    if (!res.ok) { alert(data.error || "Không xoá được"); return; }
    selected.delete(user);
  } catch (e) {
    alert("Không gọi được máy chủ: " + e.message);
  }
  refresh();
}

async function refresh() {
  try {
    const res = await fetch("/api/state", { credentials: "same-origin" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    state = await res.json();
  } catch (e) {
    $("jobinfo").innerHTML = '<span class="err">Mất kết nối tới máy chủ</span>';
    return schedule();
  }
  $("src").textContent = state.source;
  $("dst").textContent = state.dest;
  $("meta").textContent = "config: " + state.config +
    " · song song: " + state.workers + " mailbox";
  $("usersfile").textContent = state.users_file;
  renderRows(); renderScope(); renderJob(); schedule();
}

function schedule() {
  clearTimeout(timer);
  const fast = state && state.job && state.job.running;
  timer = setTimeout(refresh, fast ? 1200 : 6000);
}

document.querySelectorAll("button[data-act]").forEach((btn) => {
  btn.onclick = async () => {
    const act = btn.dataset.act;
    const only = scope();
    const who = only.length ? only.length + " mailbox đã chọn" : "TẤT CẢ mailbox";
    if (act === "sync" && !confirm(
        "Chạy thật cho " + who + "?\n\nMail sẽ được ghi vào IceWarp.")) return;
    document.querySelectorAll("button[data-act]").forEach((b) => { b.disabled = true; });
    stick = true;
    try {
      const res = await fetch("/api/run", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: act, only: only }),
      });
      const data = await res.json();
      if (!res.ok) alert(data.error || "Không chạy được");
    } catch (e) {
      alert("Không gọi được máy chủ: " + e.message);
    }
    refresh();
  };
});

$("all").onchange = (e) => {
  selected = e.target.checked
    ? new Set(state.mailboxes.map((m) => m.src_user)) : new Set();
  renderRows(); renderScope();
};

$("addform").onsubmit = async (e) => {
  e.preventDefault();
  const form = e.target;
  const body = Object.fromEntries(new FormData(form).entries());
  const note = $("addnote");
  try {
    const res = await fetch("/api/users", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      note.innerHTML = '<span class="err">' + esc(data.error) + "</span>";
      return;
    }
    form.reset();
    note.textContent = "Đã thêm " + data.src_user + " vào danh sách.";
    refresh();
  } catch (err) {
    note.innerHTML = '<span class="err">Không gọi được máy chủ.</span>';
  }
};

$("log").onscroll = () => {
  const el = $("log");
  stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
};

refresh();
</script>
</body>
</html>
"""
