// Minimal vanilla-JS test client for the phase-9 FastAPI app.
// No framework, no build step. Open at /ui or via `python -m http.server`.

const $ = (sel) => document.querySelector(sel);
const apiBaseInput = $("#api-base");
const threadList = $("#threads");
const messagesEl = $("#messages");
const threadMeta = $("#thread-meta");
const composer = $("#composer");
const composerInput = $("#composer-input");
const sendBtn = $("#send-btn");
const newThreadBtn = $("#new-thread");
const statusEl = $("#status");

let activeThreadId = localStorage.getItem("activeThreadId") || null;

function apiBase() {
  return apiBaseInput.value.replace(/\/+$/, "");
}

function setStatus(msg, isError = false) {
  statusEl.textContent = msg || "";
  statusEl.classList.toggle("error", !!isError);
}

function linkifyText(text) {
  // Escape HTML, then turn URLs into clickable anchors. Keeps output safe.
  const esc = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return esc.replace(
    /https?:\/\/[^\s<>)\]]+/g,
    (u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`
  );
}

function renderMessage(msg) {
  const li = document.createElement("li");
  const isRefusal =
    msg.role === "assistant" && /I cannot/i.test(msg.content || "");
  li.className = msg.role + (isRefusal ? " refused" : "");
  li.innerHTML =
    `<div class="role">${msg.role}${
      msg.timestamp ? " · " + msg.timestamp : ""
    }</div>` + linkifyText(msg.content || "");
  messagesEl.appendChild(li);
}

async function api(path, opts = {}) {
  const r = await fetch(apiBase() + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText}: ${detail}`);
  }
  if (r.status === 204) return null;
  return r.json();
}

async function refreshThreads() {
  try {
    const items = await api("/threads?limit=50");
    threadList.innerHTML = "";
    for (const t of items) {
      const li = document.createElement("li");
      if (t.thread_id === activeThreadId) li.classList.add("active");
      li.innerHTML =
        `<span class="tid">${t.thread_id.slice(0, 12)}…</span>` +
        `<span class="when">${t.created_at}</span>`;
      li.addEventListener("click", () => selectThread(t.thread_id));
      threadList.appendChild(li);
    }
  } catch (e) {
    setStatus("threads: " + e.message, true);
  }
}

async function selectThread(tid) {
  activeThreadId = tid;
  localStorage.setItem("activeThreadId", tid);
  threadMeta.textContent = "thread " + tid;
  messagesEl.innerHTML = "";
  await refreshThreads();
  try {
    const msgs = await api(`/threads/${tid}/messages`);
    msgs.forEach(renderMessage);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    setStatus("");
  } catch (e) {
    setStatus("history: " + e.message, true);
  }
}

newThreadBtn.addEventListener("click", async () => {
  try {
    const t = await api("/threads", {
      method: "POST",
      body: JSON.stringify({}),
    });
    await selectThread(t.thread_id);
  } catch (e) {
    setStatus("create thread: " + e.message, true);
  }
});

composer.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const content = composerInput.value.trim();
  if (!content) return;
  if (!activeThreadId) {
    setStatus("Create or select a thread first.", true);
    return;
  }
  sendBtn.disabled = true;
  setStatus("…thinking");
  renderMessage({
    role: "user",
    content,
    timestamp: new Date().toISOString(),
  });
  composerInput.value = "";
  messagesEl.scrollTop = messagesEl.scrollHeight;
  try {
    const res = await api(`/threads/${activeThreadId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    renderMessage({
      role: "assistant",
      content: res.assistant_message,
      timestamp: new Date().toISOString(),
    });
    messagesEl.scrollTop = messagesEl.scrollHeight;
    if (res.debug) {
      setStatus(
        `route=${res.debug.route_reason} model=${res.debug.model} ` +
          `latency=${res.debug.latency_ms}ms ` +
          `retried=${res.debug.retried} fallback=${res.debug.used_fallback}`
      );
    } else {
      setStatus("");
    }
  } catch (e) {
    setStatus("send: " + e.message, true);
  } finally {
    sendBtn.disabled = false;
  }
});

// Boot.
(async () => {
  await refreshThreads();
  if (activeThreadId) await selectThread(activeThreadId);
})();
