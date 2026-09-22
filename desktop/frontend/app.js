"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  workspace: "",
  currentFile: null,
  dirty: false,
  runId: null,
  source: null,
};

function setRunState(mode) {
  const el = $("run-state");
  el.className = "run-state " + mode;
  $("send").disabled = mode === "running";
}

function addMessage(kind, text, meta) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + (kind === "user" ? "user" : kind === "system" ? "system" : "agent");
  if (kind === "step") wrap.className = "msg step";
  if (kind === "task") wrap.className = "msg task";
  if (kind === "done") wrap.className = "msg done";
  if (kind === "error") wrap.className = "msg error";
  if (meta) {
    const m = document.createElement("span");
    m.className = "meta";
    m.textContent = meta;
    wrap.appendChild(m);
  }
  const body = document.createElement("span");
  body.textContent = text;
  wrap.appendChild(body);
  const box = $("messages");
  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
  return wrap;
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

/* ---------- workspace + tree ---------- */

async function setWorkspace() {
  const path = $("workspace").value.trim();
  if (!path) return;
  try {
    const data = await api("/api/workspace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    state.workspace = data.workspace;
    await loadTree("");
  } catch (err) {
    addMessage("error", String(err.message));
  }
}

function treeNode(name, type, rel) {
  const el = document.createElement("span");
  el.className = type === "dir" ? "folder-name" : "file";
  el.textContent = name;
  if (type === "dir") {
    const summary = document.createElement("summary");
    summary.appendChild(el);
    const details = document.createElement("details");
    details.appendChild(summary);
    const children = document.createElement("div");
    children.className = "children";
    details.appendChild(children);
    details.addEventListener("toggle", async () => {
      if (details.open && !children.dataset.loaded) {
        children.dataset.loaded = "1";
        await loadTree(rel, children);
      }
    });
    return details;
  }
  el.addEventListener("click", () => openFile(rel));
  return el;
}

async function loadTree(path, container) {
  const target = container || $("tree");
  target.textContent = "";
  try {
    const data = await api("/api/tree?path=" + encodeURIComponent(path));
    for (const dir of data.dirs) target.appendChild(treeNode(dir.name, "dir", joinRel(path, dir.name)));
    for (const file of data.files) target.appendChild(treeNode(file.name, "file", joinRel(path, file.name)));
    if (!data.dirs.length && !data.files.length && path === "") {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "空目录";
      target.appendChild(empty);
    }
  } catch (err) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = String(err.message);
    target.appendChild(empty);
  }
}

function joinRel(base, name) {
  return base ? base + "/" + name : name;
}

/* ---------- editor ---------- */

async function openFile(path) {
  if (state.dirty && !confirm("当前文件未保存，继续打开其他文件？")) return;
  try {
    const data = await api("/api/file?path=" + encodeURIComponent(path));
    state.currentFile = path;
    state.dirty = false;
    $("file-path").textContent = path;
    $("code").value = data.content;
    $("save").disabled = true;
    document.querySelectorAll(".tree .file.active").forEach((el) => el.classList.remove("active"));
    updateLineNumbers();
  } catch (err) {
    addMessage("error", String(err.message));
  }
}

async function saveFile() {
  if (!state.currentFile) return;
  try {
    await api("/api/file", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.currentFile, content: $("code").value }),
    });
    state.dirty = false;
    $("save").disabled = true;
  } catch (err) {
    addMessage("error", String(err.message));
  }
}

function updateLineNumbers() {
  const code = $("code");
  const count = code.value.split("\n").length;
  const lines = [];
  for (let i = 1; i <= count; i++) lines.push(i);
  $("line-numbers").textContent = lines.join("\n");
}

/* ---------- chat ---------- */

async function sendGoal() {
  const goal = $("goal").value.trim();
  if (!goal || state.runId) return;
  const techStack = $("tech-stack").value.trim();
  $("goal").value = "";
  addMessage("user", goal, techStack ? "技术栈: " + techStack : null);
  try {
    const data = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal, tech_stack: techStack }),
    });
    state.runId = data.run_id;
    setRunState("running");
    addMessage("system", "任务已提交，正在执行…");
    openEventStream(data.run_id);
  } catch (err) {
    addMessage("error", String(err.message));
  }
}

function openEventStream(runId) {
  const source = new EventSource("/api/events?run_id=" + runId);
  state.source = source;
  source.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.kind === "user" || data.kind === "system") return;
    if (data.kind === "step") {
      addMessage("step", data.text);
    } else if (data.kind === "task") {
      addMessage("task", data.text);
    } else if (data.kind === "done") {
      addMessage("done", data.text);
      finishRun();
    } else if (data.kind === "error") {
      addMessage("error", data.text);
      finishRun("error");
    }
  };
  source.onerror = () => {
    if (state.runId !== null) {
      source.close();
      finishRun("error");
    }
  };
}

function finishRun(mode) {
  if (state.source) {
    state.source.close();
    state.source = null;
  }
  if (mode === "error") addMessage("error", "与后端的连接中断");
  state.runId = null;
  setRunState(mode === "error" ? "error" : "done");
  loadTree("");
}

/* ---------- wiring ---------- */

async function init() {
  try {
    const status = await api("/api/status");
    state.workspace = status.workspace;
    $("workspace").value = status.workspace;
    const chip = $("status-chip");
    if (status.key_configured) {
      chip.textContent = status.model + " 已连接";
      chip.className = "chip ok";
    } else {
      chip.textContent = status.model + " 未配置密钥";
      chip.className = "chip warn";
    }
    await loadTree("");
  } catch (err) {
    const chip = $("status-chip");
    chip.textContent = "后端不可用";
    chip.className = "chip warn";
  }

  $("ws-set").addEventListener("click", setWorkspace);
  $("workspace").addEventListener("keydown", (e) => {
    if (e.key === "Enter") setWorkspace();
  });
  $("refresh-tree").addEventListener("click", () => loadTree(""));
  $("save").addEventListener("click", saveFile);
  $("code").addEventListener("input", () => {
    state.dirty = true;
    $("save").disabled = false;
    updateLineNumbers();
  });
  $("code").addEventListener("scroll", () => {
    $("line-numbers").scrollTop = $("code").scrollTop;
  });
  $("code").addEventListener("keydown", (e) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const start = $("code").selectionStart;
      const end = $("code").selectionEnd;
      $("code").setRangeText("    ", start, end, "end");
      $("code").dispatchEvent(new Event("input"));
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      saveFile();
    }
  });
  $("send").addEventListener("click", sendGoal);
  $("goal").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendGoal();
    }
  });
}

init();
