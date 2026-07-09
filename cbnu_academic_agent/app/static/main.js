const form = document.getElementById("chat-form");
const input = document.getElementById("message");
const messages = document.getElementById("messages");
const uploadForm = document.getElementById("upload-form");
const profilePdf = document.getElementById("profile-pdf");
const uploadStatus = document.getElementById("upload-status");
const syncBtn = document.getElementById("sync-btn");
const syncStatus = document.getElementById("sync-status");
const calendarList = document.getElementById("calendar-list");
const changeList = document.getElementById("change-list");
const refreshCalendar = document.getElementById("refresh-calendar");
const refreshChanges = document.getElementById("refresh-changes");
const todoForm = document.getElementById("todo-form");
const todoGoal = document.getElementById("todo-goal");
const todoList = document.getElementById("todo-list");
const sessionId = localStorage.getItem("cbnu_session_id") || crypto.randomUUID();
localStorage.setItem("cbnu_session_id", sessionId);

function addMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

function addSources(sources) {
  if (!sources || sources.length === 0) return;
  const div = document.createElement("div");
  div.className = "sources";
  div.innerHTML = "<b>출처</b><br>" + sources.map((s, idx) => {
    const safeTitle = s.title || `출처 ${idx + 1}`;
    return `${idx + 1}. <a href="${s.url}" target="_blank" rel="noreferrer">${safeTitle}</a>`;
  }).join("<br>");
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  addMessage("user", text);
  addMessage("system", "실시간 크롤링과 RAG 검색을 수행 중입니다...");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId }),
    });
    const data = await res.json();
    const systemMsgs = document.querySelectorAll(".msg.system");
    systemMsgs[systemMsgs.length - 1]?.remove();

    if (!res.ok) {
      addMessage("assistant", data.detail || "오류가 발생했습니다.");
      return;
    }
    addMessage("assistant", data.answer);
    addSources(data.sources);
    if (data.schedules && data.schedules.length > 0) {
      loadCalendar();
    }
  } catch (err) {
    addMessage("assistant", "서버와 통신하지 못했습니다. FastAPI 서버 실행 상태를 확인하세요.");
  }
});

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = profilePdf.files[0];
  if (!file) {
    uploadStatus.textContent = "PDF 파일을 선택하세요.";
    return;
  }

  const body = new FormData();
  body.append("file", file);
  uploadStatus.textContent = "업로드 중...";

  const res = await fetch("/api/profile/upload", { method: "POST", body });
  const data = await res.json();
  uploadStatus.textContent = res.ok
    ? `${data.filename} 저장 완료 (${data.chunks} chunks)`
    : data.detail || "업로드 실패";
});

syncBtn.addEventListener("click", async () => {
  syncStatus.textContent = "동기화 중...";
  const res = await fetch("/api/crawl/sync", { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    syncStatus.textContent = data.detail || "동기화 실패";
    return;
  }
  syncStatus.textContent = `신규 ${data.new_count}, 변경 ${data.changed_count}, 동일 ${data.unchanged_count}, 색인 ${data.indexed_documents}`;
  loadCalendar();
  loadChanges();
});

todoForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const goal = todoGoal.value.trim();
  if (!goal) return;
  todoList.innerHTML = "<li>분해 중...</li>";
  const res = await fetch("/api/todos/breakdown", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal }),
  });
  const data = await res.json();
  if (!res.ok) {
    todoList.innerHTML = `<li>${data.detail || "Todo 생성 실패"}</li>`;
    return;
  }
  todoList.innerHTML = data.todos.map((todo) => (
    `<li><b>${todo.title}</b><span>${todo.due_date || "날짜 미정"} · ${todo.priority}</span><small>${todo.reason || ""}</small></li>`
  )).join("");
});

refreshCalendar.addEventListener("click", loadCalendar);
refreshChanges.addEventListener("click", loadChanges);

async function loadCalendar() {
  const res = await fetch("/api/calendar");
  const events = await res.json();
  if (!res.ok || events.length === 0) {
    calendarList.innerHTML = "<p class=\"empty-text\">표시할 일정이 없습니다.</p>";
    return;
  }
  calendarList.innerHTML = events.map((event) => {
    const date = event.deadline || event.start_date || event.end_date || "날짜 미정";
    const source = event.source_url
      ? `<a href="${event.source_url}" target="_blank" rel="noreferrer">출처</a>`
      : "";
    return `<article class="calendar-item">
      <time>${date}</time>
      <div>
        <b>${event.title}</b>
        <span>${event.category} · ${event.importance} · ${event.change_type}</span>
        <p>${event.evidence || ""}</p>
        ${source}
      </div>
    </article>`;
  }).join("");
}

async function loadChanges() {
  const res = await fetch("/api/changes");
  const changes = await res.json();
  if (!res.ok || changes.length === 0) {
    changeList.innerHTML = "<p class=\"empty-text\">변경 감지 내역이 없습니다.</p>";
    return;
  }
  changeList.innerHTML = changes.map((item) => (
    `<article class="change-item">
      <b>${item.change_type.toUpperCase()}</b>
      <a href="${item.source_url}" target="_blank" rel="noreferrer">${item.title}</a>
      <span>${item.detected_at}</span>
    </article>`
  )).join("");
}

loadCalendar();
loadChanges();
