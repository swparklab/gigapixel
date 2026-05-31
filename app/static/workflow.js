/* global LiteGraph, LGraph, LGraphCanvas */

const socketStatusEl = document.getElementById("socketStatus");
const eventLogEl = document.getElementById("eventLog");
const runSummaryEl = document.getElementById("runSummary");
const uploadFilesEl = document.getElementById("nodeFiles");
const uploadBtnEl = document.getElementById("uploadBatchBtn");
const uploadSelectEl = document.getElementById("uploadSelect");
const libraryListEl = document.getElementById("libraryList");
const runGraphBtnEl = document.getElementById("runGraphBtn");
const seedGraphBtnEl = document.getElementById("seedGraphBtn");
const classicLinkEl = document.getElementById("classicLink");
const brandTitleEl = document.getElementById("brandTitle");
const brandSubtitleEl = document.getElementById("brandSubtitle");
const langLabelEl = document.getElementById("langLabel");
const themeLabelEl = document.getElementById("themeLabel");
const uploadPanelTitleEl = document.getElementById("uploadPanelTitle");
const libraryPanelTitleEl = document.getElementById("libraryPanelTitle");
const statusPanelTitleEl = document.getElementById("statusPanelTitle");
const eventsPanelTitleEl = document.getElementById("eventsPanelTitle");
const langSelectEl = document.getElementById("langSelect");
const themeSelectEl = document.getElementById("themeSelect");
const canvasEl = document.getElementById("graphCanvas");

let ws = null;
let graph = null;
let graphCanvas = null;
let selectedUploadId = "";
let lastLibrary = [];
let socketStateKey = "connecting";

const typeColors = {
  flow: "#ffd166",
  session: "#4cc9f0",
  upload_ref: "#f72585",
  string: "#90be6d",
  int: "#ff9f1c",
  float: "#9b5de5",
  url: "#06d6a0",
};

const i18n = {
  en: {
    pageTitle: "Gigapixel Node Workflow",
    brandTitle: "Gigapixel Node Studio",
    brandSubtitle: "Local Web Agent Workflow",
    langLabel: "Language",
    themeLabel: "Theme",
    lightMode: "Light",
    darkMode: "Night",
    classicUi: "Classic UI",
    seedGraph: "Create Seed Graph",
    runGraph: "Run Graph",
    uploadBatchTitle: "Upload Batch",
    uploadBatchBtn: "Upload Batch",
    libraryTitle: "Function Library",
    statusTitle: "Status",
    eventsTitle: "Events",
    connecting: "connecting...",
    connected: "connected",
    disconnected: "disconnected",
    socketError: "socket error",
    wsConnectedLog: "WebSocket connected.",
    wsDisconnectedLog: "WebSocket disconnected. reconnecting...",
    seedGraphCreated: "Seed graph created.",
    needTwoImages: "At least 2 images are required.",
    uploadFailed: "Upload failed: {message}",
    uploadBatchCreated: "Upload batch created: {uploadId} / files={count}",
    downloadRaw: "Download Raw High-Res",
    downloadOptimized: "Download Optimized",
    rawUnavailable: "Raw download unavailable",
    optimizedUnavailable: "Optimized download unavailable",
    downloadReadyLog: "download ready: raw={raw}, optimized={optimized}",
    runStarted: "running...",
    runStartedLog: "run started",
    runCompleted: "completed",
    runCompletedLog: "run completed",
    runFailedLog: "run failed: {message}",
    flowStartedLog: "flow started: {name}",
    flowFinishedLog: "flow finished: {name}",
    errorLog: "error: {message}",
    nodeMessageLog: "node {id}: {message}",
    wsNotConnected: "WebSocket is not connected.",
    unknownError: "unknown error",
    unknown: "unknown",
    na: "n/a",
    cat_workflow: "workflow",
    cat_data: "data",
    cat_math: "math",
  },
  ko: {
    pageTitle: "기가픽셀 노드 워크플로우",
    brandTitle: "기가픽셀 노드 스튜디오",
    brandSubtitle: "로컬 웹 에이전트 워크플로우",
    langLabel: "언어",
    themeLabel: "테마",
    lightMode: "밝은 모드",
    darkMode: "밤 모드",
    classicUi: "클래식 UI",
    seedGraph: "기본 그래프 생성",
    runGraph: "그래프 실행",
    uploadBatchTitle: "배치 업로드",
    uploadBatchBtn: "배치 업로드",
    libraryTitle: "함수 라이브러리",
    statusTitle: "상태",
    eventsTitle: "이벤트",
    connecting: "연결 중...",
    connected: "연결됨",
    disconnected: "연결 끊김",
    socketError: "소켓 오류",
    wsConnectedLog: "WebSocket 연결 완료",
    wsDisconnectedLog: "WebSocket 연결이 끊어졌습니다. 재연결 중...",
    seedGraphCreated: "기본 그래프를 생성했습니다.",
    needTwoImages: "이미지는 최소 2장 이상 필요합니다.",
    uploadFailed: "업로드 실패: {message}",
    uploadBatchCreated: "배치 업로드 완료: {uploadId} / 파일={count}",
    downloadRaw: "원본 고해상도 다운로드",
    downloadOptimized: "최적화 버전 다운로드",
    rawUnavailable: "원본 다운로드를 사용할 수 없습니다",
    optimizedUnavailable: "최적화 다운로드를 사용할 수 없습니다",
    downloadReadyLog: "다운로드 준비 완료: 원본={raw}, 최적화={optimized}",
    runStarted: "실행 중...",
    runStartedLog: "그래프 실행 시작",
    runCompleted: "완료",
    runCompletedLog: "그래프 실행 완료",
    runFailedLog: "실행 실패: {message}",
    flowStartedLog: "플로우 시작: {name}",
    flowFinishedLog: "플로우 종료: {name}",
    errorLog: "오류: {message}",
    nodeMessageLog: "노드 {id}: {message}",
    wsNotConnected: "WebSocket이 연결되지 않았습니다.",
    unknownError: "알 수 없는 오류",
    unknown: "알 수 없음",
    na: "없음",
    cat_workflow: "워크플로우",
    cat_data: "데이터",
    cat_math: "수학",
  },
};

function currentLang() {
  return window.UI_PREFS ? window.UI_PREFS.getLanguage() : "en";
}

function t(key) {
  const lang = currentLang();
  const pack = i18n[lang] || i18n.en;
  return pack[key] || i18n.en[key] || key;
}

function tf(key, vars) {
  let text = t(key);
  Object.entries(vars || {}).forEach(([name, value]) => {
    text = text.replaceAll(`{${name}}`, String(value));
  });
  return text;
}

function applyTranslations() {
  document.title = t("pageTitle");
  brandTitleEl.textContent = t("brandTitle");
  brandSubtitleEl.textContent = t("brandSubtitle");
  langLabelEl.textContent = t("langLabel");
  themeLabelEl.textContent = t("themeLabel");
  classicLinkEl.textContent = t("classicUi");
  seedGraphBtnEl.textContent = t("seedGraph");
  runGraphBtnEl.textContent = t("runGraph");
  uploadPanelTitleEl.textContent = t("uploadBatchTitle");
  uploadBtnEl.textContent = t("uploadBatchBtn");
  libraryPanelTitleEl.textContent = t("libraryTitle");
  statusPanelTitleEl.textContent = t("statusTitle");
  eventsPanelTitleEl.textContent = t("eventsTitle");
  socketStatusEl.textContent = t(socketStateKey);

  if (langSelectEl) {
    langSelectEl.options[0].textContent = "한국어";
    langSelectEl.options[1].textContent = "English";
  }
  if (themeSelectEl) {
    themeSelectEl.options[0].textContent = t("lightMode");
    themeSelectEl.options[1].textContent = t("darkMode");
  }

  if (runSummaryEl.dataset.variant === "links") {
    const rawUrl = runSummaryEl.dataset.rawUrl || "";
    const optimizedUrl = runSummaryEl.dataset.optimizedUrl || "";
    const rawLink = rawUrl
      ? `<a href="${rawUrl}">${t("downloadRaw")}</a>`
      : `<span>${t("rawUnavailable")}</span>`;
    const optimizedLink = optimizedUrl
      ? `<a href="${optimizedUrl}">${t("downloadOptimized")}</a>`
      : `<span>${t("optimizedUnavailable")}</span>`;
    runSummaryEl.innerHTML = `${rawLink}<br/>${optimizedLink}`;
  }
}

function logEvent(line) {
  const now = new Date().toLocaleTimeString();
  const lines = eventLogEl.textContent ? eventLogEl.textContent.split("\n") : [];
  lines.push(`[${now}] ${line}`);
  const clipped = lines.slice(-120);
  eventLogEl.textContent = clipped.join("\n");
  eventLogEl.scrollTop = eventLogEl.scrollHeight;
}

function setSocketStatus(stateKey) {
  socketStateKey = stateKey;
  socketStatusEl.textContent = t(stateKey);
}

function resizeCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvasEl.getBoundingClientRect();
  canvasEl.width = Math.max(1, Math.floor(rect.width * dpr));
  canvasEl.height = Math.max(1, Math.floor(rect.height * dpr));
  if (graphCanvas) {
    graphCanvas.ds.scale = 1;
    graphCanvas.resize();
  }
}

function decorateCanvasColors() {
  if (!graphCanvas) return;
  graphCanvas.default_connection_color_byType = { ...typeColors };
  graphCanvas.default_connection_color_byTypeOff = { ...typeColors };
  if (LGraphCanvas && LGraphCanvas.link_type_colors) {
    Object.assign(LGraphCanvas.link_type_colors, typeColors);
  }
}

function registerNodeTypes() {
  function StartNode() {
    this.title = "Start";
    this.color = "#224366";
    this.bgcolor = "#1d3557";
    this.addOutput("flow", "flow");
    this.addOutput("ctx", "flow");
    this.properties = {
      flow_name: "flow_a",
      session_name: "Untitled Session",
      stitch_mode: "scans",
    };
    this.addWidget("text", "flow_name", this.properties.flow_name, (v) => {
      this.properties.flow_name = String(v || "flow");
    });
    this.addWidget("text", "session_name", this.properties.session_name, (v) => {
      this.properties.session_name = String(v || "Untitled Session");
    });
    this.addWidget("combo", "stitch_mode", this.properties.stitch_mode, (v) => {
      this.properties.stitch_mode = String(v || "scans");
    }, { values: ["scans", "panorama"] });
    this.serialize_widgets = true;
  }
  LiteGraph.registerNodeType("workflow/start", StartNode);

  function UploadRefNode() {
    this.title = "UploadRef";
    this.color = "#7d1d4e";
    this.bgcolor = "#9a1f5c";
    this.addOutput("upload_ref", "upload_ref");
    this.properties = { upload_id: "" };
    this.addWidget("text", "upload_id", this.properties.upload_id, (v) => {
      this.properties.upload_id = String(v || "");
    });
    this.serialize_widgets = true;
  }
  LiteGraph.registerNodeType("data/upload_ref", UploadRefNode);

  function StringNode() {
    this.title = "String";
    this.color = "#1d5f38";
    this.bgcolor = "#2f855a";
    this.addOutput("value", "string");
    this.properties = { value: "" };
    this.addWidget("text", "value", this.properties.value, (v) => {
      this.properties.value = String(v || "");
    });
    this.serialize_widgets = true;
  }
  LiteGraph.registerNodeType("data/string", StringNode);

  function IntNode() {
    this.title = "Int";
    this.color = "#7a4a00";
    this.bgcolor = "#a16207";
    this.addOutput("value", "int");
    this.properties = { value: 0 };
    this.addWidget("number", "value", this.properties.value, (v) => {
      this.properties.value = parseInt(v, 10) || 0;
    }, { step: 1 });
    this.serialize_widgets = true;
  }
  LiteGraph.registerNodeType("data/int", IntNode);

  function FloatNode() {
    this.title = "Float";
    this.color = "#4f2c7a";
    this.bgcolor = "#6a3ea1";
    this.addOutput("value", "float");
    this.properties = { value: 0.0 };
    this.addWidget("number", "value", this.properties.value, (v) => {
      this.properties.value = Number(v || 0);
    }, { step: 0.1, precision: 3 });
    this.serialize_widgets = true;
  }
  LiteGraph.registerNodeType("data/float", FloatNode);

  function AddIntNode() {
    this.title = "AddInt";
    this.color = "#8f5b14";
    this.bgcolor = "#b7791f";
    this.addInput("a", "int");
    this.addInput("b", "int");
    this.addOutput("sum", "int");
  }
  LiteGraph.registerNodeType("math/add_int", AddIntNode);

  function AddFloatNode() {
    this.title = "AddFloat";
    this.color = "#5f3d8a";
    this.bgcolor = "#7a4fb0";
    this.addInput("a", "float");
    this.addInput("b", "float");
    this.addOutput("sum", "float");
  }
  LiteGraph.registerNodeType("math/add_float", AddFloatNode);

  function RunPipelineNode() {
    this.title = "RunPipeline";
    this.color = "#0f4c5c";
    this.bgcolor = "#146c80";
    this.addInput("ctx", "flow");
    this.addInput("ctx_alt", "flow");
    this.addInput("upload_ref", "upload_ref");
    this.addInput("session_name", "string");
    this.addInput("stitch_mode", "string");
    this.addOutput("flow", "flow");
    this.addOutput("session", "session");
    this.properties = { session_name: "Untitled Session", stitch_mode: "scans", upload_id: "" };
    this.addWidget("text", "fallback_name", this.properties.session_name, (v) => {
      this.properties.session_name = String(v || "Untitled Session");
    });
    this.addWidget("combo", "fallback_mode", this.properties.stitch_mode, (v) => {
      this.properties.stitch_mode = String(v || "scans");
    }, { values: ["scans", "panorama"] });
    this.addWidget("text", "fallback_upload", this.properties.upload_id, (v) => {
      this.properties.upload_id = String(v || "");
    });
    this.serialize_widgets = true;
  }
  LiteGraph.registerNodeType("workflow/run_pipeline", RunPipelineNode);

  function DownloadNode() {
    this.title = "Download";
    this.color = "#0f766e";
    this.bgcolor = "#0d9488";
    this.addInput("flow", "flow");
    this.addInput("session", "session");
    this.addOutput("flow", "flow");
    this.addOutput("url", "url");
  }
  LiteGraph.registerNodeType("workflow/download", DownloadNode);
}

function setNodeVisualState(nodeId, state) {
  const node = graph ? graph.getNodeById(Number(nodeId)) : null;
  if (!node) return;
  if (state === "running") {
    node.boxcolor = "#f59e0b";
  } else if (state === "done") {
    node.boxcolor = "#10b981";
  } else if (state === "error") {
    node.boxcolor = "#ef4444";
  } else {
    node.boxcolor = "#666";
  }
  if (graphCanvas) graphCanvas.setDirty(true, true);
}

function populateLibrary(list) {
  lastLibrary = Array.isArray(list) ? list : [];
  libraryListEl.innerHTML = "";
  lastLibrary.forEach((item) => {
    const li = document.createElement("li");
    const cat = t(`cat_${item.category}`);
    li.textContent = `${cat} / ${item.title} (${item.type})`;
    libraryListEl.appendChild(li);
  });
}

function applyUploadIdToUploadNodes(uploadId) {
  if (!graph || !uploadId) return;
  graph._nodes
    .filter((n) => n.type === "data/upload_ref")
    .forEach((n) => {
      n.properties.upload_id = uploadId;
      if (n.widgets && n.widgets[0]) n.widgets[0].value = uploadId;
    });
  graphCanvas.setDirty(true, true);
}

function seedGraph() {
  graph.clear();

  const start = LiteGraph.createNode("workflow/start");
  const upload = LiteGraph.createNode("data/upload_ref");
  const runPipe = LiteGraph.createNode("workflow/run_pipeline");
  const download = LiteGraph.createNode("workflow/download");

  start.pos = [60, 70];
  upload.pos = [60, 260];
  runPipe.pos = [420, 90];
  download.pos = [790, 130];

  graph.add(start);
  graph.add(upload);
  graph.add(runPipe);
  graph.add(download);

  if (selectedUploadId) {
    upload.properties.upload_id = selectedUploadId;
    if (upload.widgets && upload.widgets[0]) upload.widgets[0].value = selectedUploadId;
    runPipe.properties.upload_id = selectedUploadId;
    if (runPipe.widgets && runPipe.widgets[2]) runPipe.widgets[2].value = selectedUploadId;
  }

  start.connect(0, runPipe, 0);
  start.connect(1, runPipe, 1);
  upload.connect(0, runPipe, 2);
  runPipe.connect(0, download, 0);
  runPipe.connect(1, download, 1);

  graphCanvas.setDirty(true, true);
  logEvent(t("seedGraphCreated"));
}

async function uploadBatch() {
  const files = uploadFilesEl.files;
  if (!files || files.length < 2) {
    alert(t("needTwoImages"));
    return;
  }

  const form = new FormData();
  Array.from(files).forEach((file) => form.append("files", file));

  const res = await fetch("/api/node/uploads", {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(tf("uploadFailed", { message: text }));
  }
  const data = await res.json();
  selectedUploadId = data.upload_id;

  const option = document.createElement("option");
  option.value = data.upload_id;
  option.textContent = `${data.upload_id} (${data.count})`;
  option.selected = true;
  uploadSelectEl.appendChild(option);

  applyUploadIdToUploadNodes(data.upload_id);
  logEvent(tf("uploadBatchCreated", { uploadId: data.upload_id, count: data.count }));
}

async function refreshUploadList() {
  const res = await fetch("/api/node/uploads");
  if (!res.ok) return;
  const data = await res.json();
  uploadSelectEl.innerHTML = "";
  (data.uploads || []).forEach((item) => {
    const option = document.createElement("option");
    option.value = item.upload_id;
    option.textContent = `${item.upload_id} (${item.count})`;
    uploadSelectEl.appendChild(option);
  });
  if (uploadSelectEl.options.length > 0) {
    selectedUploadId = uploadSelectEl.value;
    applyUploadIdToUploadNodes(selectedUploadId);
  }
}

function connectSocket() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${scheme}://${window.location.host}/ws/workflow`);

  ws.onopen = () => {
    setSocketStatus("connected");
    logEvent(t("wsConnectedLog"));
    ws.send(JSON.stringify({ action: "get_library" }));
  };

  ws.onmessage = (evt) => {
    const message = JSON.parse(evt.data);
    const event = message.event;
    const payload = message.payload || {};

    if (event === "hello" || event === "library") {
      Object.assign(typeColors, payload.type_colors || {});
      decorateCanvasColors();
      populateLibrary(payload.node_library || []);
      return;
    }

    if (event === "node_state") {
      setNodeVisualState(payload.node_id, payload.state);
      if (payload.message) logEvent(tf("nodeMessageLog", { id: payload.node_id, message: payload.message }));
      return;
    }

    if (event === "package_ready") {
      const rawUrl = payload.raw_download_url || payload.download_url;
      const optimizedUrl = payload.optimized_download_url;

      const rawLink = rawUrl
        ? `<a href="${rawUrl}">${t("downloadRaw")}</a>`
        : `<span>${t("rawUnavailable")}</span>`;
      const optimizedLink = optimizedUrl
        ? `<a href="${optimizedUrl}">${t("downloadOptimized")}</a>`
        : `<span>${t("optimizedUnavailable")}</span>`;

      runSummaryEl.dataset.variant = "links";
      runSummaryEl.dataset.rawUrl = rawUrl || "";
      runSummaryEl.dataset.optimizedUrl = optimizedUrl || "";
      runSummaryEl.innerHTML = `${rawLink}<br/>${optimizedLink}`;
      logEvent(tf("downloadReadyLog", { raw: rawUrl || t("na"), optimized: optimizedUrl || t("na") }));
      return;
    }

    if (event === "run_started") {
      runSummaryEl.dataset.variant = "text";
      runSummaryEl.textContent = t("runStarted");
      logEvent(t("runStartedLog"));
      return;
    }

    if (event === "run_complete") {
      runSummaryEl.dataset.variant = "text";
      runSummaryEl.textContent = t("runCompleted");
      logEvent(t("runCompletedLog"));
      return;
    }

    if (event === "run_failed") {
      runSummaryEl.dataset.variant = "text";
      runSummaryEl.textContent = payload.message || t("unknownError");
      logEvent(tf("runFailedLog", { message: payload.message || t("unknownError") }));
      return;
    }

    if (event === "flow_started") {
      logEvent(tf("flowStartedLog", { name: payload.flow_name }));
      return;
    }

    if (event === "flow_finished") {
      logEvent(tf("flowFinishedLog", { name: payload.flow_name }));
      return;
    }

    if (event === "error") {
      logEvent(tf("errorLog", { message: payload.message || t("unknown") }));
      return;
    }

    if (event === "pong") return;
    logEvent(`${event}: ${JSON.stringify(payload)}`);
  };

  ws.onclose = () => {
    setSocketStatus("disconnected");
    logEvent(t("wsDisconnectedLog"));
    setTimeout(connectSocket, 1200);
  };

  ws.onerror = () => {
    setSocketStatus("socketError");
  };
}

function runGraph() {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    alert(t("wsNotConnected"));
    return;
  }
  const payload = graph.serialize();
  ws.send(JSON.stringify({ action: "run_graph", graph: payload }));
}

function initGraph() {
  registerNodeTypes();
  graph = new LGraph();
  graphCanvas = new LGraphCanvas(canvasEl, graph);
  decorateCanvasColors();
  resizeCanvas();
}

uploadBtnEl.addEventListener("click", async () => {
  try {
    await uploadBatch();
  } catch (err) {
    logEvent(err.message || String(err));
    alert(err.message || String(err));
  }
});

uploadSelectEl.addEventListener("change", () => {
  selectedUploadId = uploadSelectEl.value;
  applyUploadIdToUploadNodes(selectedUploadId);
});

runGraphBtnEl.addEventListener("click", runGraph);
seedGraphBtnEl.addEventListener("click", seedGraph);
window.addEventListener("resize", resizeCanvas);

if (window.UI_PREFS) {
  window.UI_PREFS.bindSelectors({
    languageSelectorId: "langSelect",
    themeSelectorId: "themeSelect",
  });
  window.UI_PREFS.onChange(() => {
    applyTranslations();
    populateLibrary(lastLibrary);
  });
} else {
  applyTranslations();
}

initGraph();
connectSocket();
refreshUploadList().catch(() => {});
