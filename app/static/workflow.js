/* global LiteGraph, LGraph, LGraphCanvas */

const ROLE_STORAGE_KEY = "ghv.workflow.role";
const DEFAULT_ROLE = "builder";
const MAX_LOG_LINES = 180;
const SOCKET_RECONNECT_BASE_MS = 1200;

const TYPE_COLORS = {
  flow: "#ffd166",
  session: "#4cc9f0",
  upload_ref: "#f72585",
  string: "#90be6d",
  int: "#ff9f1c",
  float: "#9b5de5",
  url: "#06d6a0",
  stage: "#5b8cff",
};

const ROLE_CONFIG = {
  observer: {
    canRun: false,
    canUpload: false,
    canEdit: false,
    canSeed: false,
    permissionKey: "permissionObserver",
  },
  operator: {
    canRun: true,
    canUpload: true,
    canEdit: false,
    canSeed: false,
    permissionKey: "permissionOperator",
  },
  builder: {
    canRun: true,
    canUpload: true,
    canEdit: true,
    canSeed: true,
    permissionKey: "permissionBuilder",
  },
};

const el = {
  brandTitle: document.getElementById("brandTitle"),
  brandSubtitle: document.getElementById("brandSubtitle"),
  roleLabel: document.getElementById("roleLabel"),
  roleSelect: document.getElementById("roleSelect"),
  langLabel: document.getElementById("langLabel"),
  langSelect: document.getElementById("langSelect"),
  themeLabel: document.getElementById("themeLabel"),
  themeSelect: document.getElementById("themeSelect"),
  classicLink: document.getElementById("classicLink"),

  libraryPanelTitle: document.getElementById("libraryPanelTitle"),
  libraryCountBadge: document.getElementById("libraryCountBadge"),
  librarySearchLabel: document.getElementById("librarySearchLabel"),
  librarySearchInput: document.getElementById("librarySearchInput"),
  libraryCategoryLabel: document.getElementById("libraryCategoryLabel"),
  libraryCategorySelect: document.getElementById("libraryCategorySelect"),
  libraryList: document.getElementById("libraryList"),

  uploadPanelTitle: document.getElementById("uploadPanelTitle"),
  nodeFiles: document.getElementById("nodeFiles"),
  uploadBatchBtn: document.getElementById("uploadBatchBtn"),
  applyUploadBtn: document.getElementById("applyUploadBtn"),
  uploadSelectLabel: document.getElementById("uploadSelectLabel"),
  uploadSelect: document.getElementById("uploadSelect"),
  uploadHint: document.getElementById("uploadHint"),

  quickPanelTitle: document.getElementById("quickPanelTitle"),
  seedGraphBtn: document.getElementById("seedGraphBtn"),
  resetViewBtn: document.getElementById("resetViewBtn"),
  shortcutHint: document.getElementById("shortcutHint"),

  socketStatusBadge: document.getElementById("socketStatusBadge"),
  selectedNodeBadge: document.getElementById("selectedNodeBadge"),
  zoomBadge: document.getElementById("zoomBadge"),
  zoomOutBtn: document.getElementById("zoomOutBtn"),
  zoomInBtn: document.getElementById("zoomInBtn"),
  zoomFitBtn: document.getElementById("zoomFitBtn"),
  centerNodeBtn: document.getElementById("centerNodeBtn"),
  graphCanvas: document.getElementById("graphCanvas"),

  runPanelTitle: document.getElementById("runPanelTitle"),
  permissionHint: document.getElementById("permissionHint"),
  runGraphBtn: document.getElementById("runGraphBtn"),
  clearLogBtn: document.getElementById("clearLogBtn"),
  runSummary: document.getElementById("runSummary"),
  downloadLinks: document.getElementById("downloadLinks"),

  inspectorPanelTitle: document.getElementById("inspectorPanelTitle"),
  inspectorEmpty: document.getElementById("inspectorEmpty"),
  nodeInspector: document.getElementById("nodeInspector"),

  eventsPanelTitle: document.getElementById("eventsPanelTitle"),
  eventLog: document.getElementById("eventLog"),
  toastStack: document.getElementById("toastStack"),
};

const i18n = {
  en: {
    pageTitle: "Hyper Gigapixel Agent · Node Studio",
    brandTitle: "Hyper Gigapixel Agent · Node Studio",
    brandSubtitle: "Agent Workflow Console",
    roleLabel: "Role",
    roleObserver: "Observer",
    roleOperator: "Operator",
    roleBuilder: "Builder",
    langLabel: "Language",
    themeLabel: "Theme",
    lightMode: "Light",
    darkMode: "Night",
    classicUi: "Classic UI",
    libraryPanelTitle: "Node Palette",
    librarySearchLabel: "Node Search",
    librarySearchPlaceholder: "Search nodes by name/type",
    libraryCategoryLabel: "Category Filter",
    libraryAllCategories: "All Categories",
    libraryEmpty: "No nodes match current filter.",
    addNode: "Add Node",
    uploadPanelTitle: "Input Batches",
    uploadBatchBtn: "Upload Batch",
    applyUploadBtn: "Apply To Upload Nodes",
    uploadSelectLabel: "Available Batches",
    uploadHint: "Choose a batch and route it into upload nodes.",
    noUploads: "No uploaded batch",
    quickPanelTitle: "Quick Actions",
    seedGraphBtn: "Seed Default Graph",
    resetViewBtn: "Reset View",
    shortcutHint: "Shortcuts: Ctrl/Cmd+Enter Run, Ctrl/Cmd+K Search, F Fit, Shift+S Seed",
    runPanelTitle: "Run Control",
    permissionObserver: "Observer: read-only mode. You can inspect graph and logs.",
    permissionOperator: "Operator: run/upload available. Graph editing is locked for safety.",
    permissionBuilder: "Builder: full control. You can add/edit nodes and execute workflows.",
    runGraphBtn: "Run Graph",
    clearLogBtn: "Clear Log",
    runIdle: "Ready. Configure nodes and run.",
    runRequested: "Run requested...",
    runStarted: "Running...",
    runCompleted: "Completed.",
    runFailed: "Run failed: {message}",
    downloadReady: "Download is ready.",
    sessionCreated: "Session created from node: {name} (upload: {uploadId})",
    inspectorPanelTitle: "Node Inspector",
    inspectorEmpty: "Select a node to inspect details.",
    eventsPanelTitle: "Agent Event Stream",
    socketConnecting: "connecting...",
    socketConnected: "connected",
    socketDisconnected: "disconnected",
    socketError: "socket error",
    selectedNode: "Selected: {name}",
    selectedNodeNone: "Selected: none",
    zoomLabel: "Zoom: {value}%",
    wsConnectedLog: "WebSocket connected.",
    wsDisconnectedLog: "WebSocket disconnected. reconnecting...",
    wsErrorLog: "WebSocket error detected.",
    wsNotConnected: "WebSocket is not connected yet.",
    roleSaved: "Role switched to {role}.",
    deniedRun: "This role cannot run workflows.",
    deniedUpload: "This role cannot upload batches.",
    deniedEdit: "This role cannot edit graph nodes.",
    deniedSeed: "This role cannot seed a graph.",
    needTwoImages: "At least 2 images are required.",
    uploadCreated: "Upload batch created: {uploadId} / files={count}",
    uploadApplied: "Applied upload_id={uploadId} to upload nodes.",
    uploadFailed: "Upload failed: {message}",
    graphSeeded: "Default graph has been seeded.",
    autoRunGraphPrepared: "Default graph was auto-prepared for run.",
    viewReset: "Viewport reset to default.",
    fitDone: "Viewport fitted to graph.",
    centeredNode: "Viewport centered on node {nodeId}.",
    centeredEmpty: "Select a node first.",
    logCleared: "Event log cleared.",
    downloadRaw: "Download Raw BigTIFF",
    downloadOptimized: "Download Optimized",
    rawUnavailable: "Raw image unavailable",
    optimizedUnavailable: "Optimized image unavailable",
    na: "n/a",
    unknown: "unknown",
    unknownError: "unknown error",
    inspectorId: "ID",
    inspectorType: "Type",
    inspectorTitle: "Title",
    inspectorPosition: "Position",
    inspectorProperties: "Properties",
    inspectorInputs: "Inputs",
    inspectorOutputs: "Outputs",
    cat_workflow: "workflow",
    cat_data: "data",
    cat_math: "math",
  },
  ko: {
    pageTitle: "하이퍼 기가픽셀 에이전트 · 노드 스튜디오",
    brandTitle: "하이퍼 기가픽셀 에이전트 · 노드 스튜디오",
    brandSubtitle: "에이전트 워크플로우 콘솔",
    roleLabel: "역할",
    roleObserver: "관찰자",
    roleOperator: "운영자",
    roleBuilder: "빌더",
    langLabel: "언어",
    themeLabel: "테마",
    lightMode: "밝은 모드",
    darkMode: "밤 모드",
    classicUi: "클래식 UI",
    libraryPanelTitle: "노드 팔레트",
    librarySearchLabel: "노드 검색",
    librarySearchPlaceholder: "노드 이름/타입 검색",
    libraryCategoryLabel: "카테고리 필터",
    libraryAllCategories: "모든 카테고리",
    libraryEmpty: "필터 조건에 맞는 노드가 없습니다.",
    addNode: "노드 추가",
    uploadPanelTitle: "입력 배치",
    uploadBatchBtn: "배치 업로드",
    applyUploadBtn: "업로드 노드에 적용",
    uploadSelectLabel: "사용 가능한 배치",
    uploadHint: "배치를 선택하고 업로드 노드로 연결하세요.",
    noUploads: "업로드된 배치 없음",
    quickPanelTitle: "빠른 실행",
    seedGraphBtn: "기본 그래프 생성",
    resetViewBtn: "뷰 초기화",
    shortcutHint: "단축키: Ctrl/Cmd+Enter 실행, Ctrl/Cmd+K 검색, F 맞춤, Shift+S 시드",
    runPanelTitle: "실행 제어",
    permissionObserver: "관찰자: 읽기 전용입니다. 그래프/로그 확인만 가능합니다.",
    permissionOperator: "운영자: 실행/업로드 가능, 그래프 편집은 안전을 위해 잠금됩니다.",
    permissionBuilder: "빌더: 전체 권한입니다. 노드 추가/편집/실행이 가능합니다.",
    runGraphBtn: "그래프 실행",
    clearLogBtn: "로그 지우기",
    runIdle: "준비 완료. 노드를 설정한 뒤 실행하세요.",
    runRequested: "실행 요청 중...",
    runStarted: "실행 중...",
    runCompleted: "완료되었습니다.",
    runFailed: "실행 실패: {message}",
    downloadReady: "다운로드가 준비되었습니다.",
    sessionCreated: "세션 생성: {name} (업로드: {uploadId})",
    inspectorPanelTitle: "노드 인스펙터",
    inspectorEmpty: "노드를 선택하면 상세 정보가 표시됩니다.",
    eventsPanelTitle: "에이전트 이벤트 스트림",
    socketConnecting: "연결 중...",
    socketConnected: "연결됨",
    socketDisconnected: "연결 끊김",
    socketError: "소켓 오류",
    selectedNode: "선택 노드: {name}",
    selectedNodeNone: "선택 노드: 없음",
    zoomLabel: "줌: {value}%",
    wsConnectedLog: "WebSocket 연결 완료",
    wsDisconnectedLog: "WebSocket 연결이 끊겼습니다. 재연결 중...",
    wsErrorLog: "WebSocket 오류가 감지되었습니다.",
    wsNotConnected: "WebSocket이 아직 연결되지 않았습니다.",
    roleSaved: "{role} 역할로 전환되었습니다.",
    deniedRun: "현재 역할은 워크플로우 실행 권한이 없습니다.",
    deniedUpload: "현재 역할은 배치 업로드 권한이 없습니다.",
    deniedEdit: "현재 역할은 그래프 편집 권한이 없습니다.",
    deniedSeed: "현재 역할은 기본 그래프 생성 권한이 없습니다.",
    needTwoImages: "이미지는 최소 2장 이상 필요합니다.",
    uploadCreated: "배치 업로드 완료: {uploadId} / 파일={count}",
    uploadApplied: "upload_id={uploadId} 를 업로드 노드에 적용했습니다.",
    uploadFailed: "업로드 실패: {message}",
    graphSeeded: "기본 그래프를 생성했습니다.",
    autoRunGraphPrepared: "실행을 위해 기본 그래프를 자동 구성했습니다.",
    viewReset: "뷰포트를 기본 위치로 되돌렸습니다.",
    fitDone: "그래프에 맞게 뷰포트를 조정했습니다.",
    centeredNode: "노드 {nodeId} 기준으로 화면을 이동했습니다.",
    centeredEmpty: "먼저 노드를 선택하세요.",
    logCleared: "이벤트 로그를 비웠습니다.",
    downloadRaw: "원본 BigTIFF 다운로드",
    downloadOptimized: "최적화 버전 다운로드",
    rawUnavailable: "원본 이미지를 찾을 수 없습니다",
    optimizedUnavailable: "최적화 이미지를 찾을 수 없습니다",
    na: "없음",
    unknown: "알 수 없음",
    unknownError: "알 수 없는 오류",
    inspectorId: "ID",
    inspectorType: "타입",
    inspectorTitle: "타이틀",
    inspectorPosition: "좌표",
    inspectorProperties: "속성",
    inspectorInputs: "입력",
    inspectorOutputs: "출력",
    cat_workflow: "워크플로우",
    cat_data: "데이터",
    cat_math: "수학",
  },
};

let ws = null;
let wsReconnectTimer = null;
let pingTimer = null;
let reconnectDelay = SOCKET_RECONNECT_BASE_MS;

let graph = null;
let graphCanvas = null;
let nodeTypesRegistered = false;
let selectedNode = null;
let selectedUploadId = "";
let lastLibrary = [];
let socketStateKey = "socketConnecting";
let runCount = 0;
let role = loadRole();

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

function currentPermissions() {
  return ROLE_CONFIG[role] || ROLE_CONFIG[DEFAULT_ROLE];
}

function loadRole() {
  try {
    const saved = window.localStorage.getItem(ROLE_STORAGE_KEY);
    if (saved && ROLE_CONFIG[saved]) return saved;
  } catch (_) {
    // Ignore storage errors.
  }
  return DEFAULT_ROLE;
}

function saveRole(nextRole) {
  try {
    window.localStorage.setItem(ROLE_STORAGE_KEY, nextRole);
  } catch (_) {
    // Ignore storage errors.
  }
}

function readRoleLabel(roleValue) {
  if (roleValue === "observer") return t("roleObserver");
  if (roleValue === "operator") return t("roleOperator");
  return t("roleBuilder");
}

function isTypingContext(target) {
  if (!target) return false;
  const tag = (target.tagName || "").toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || Boolean(target.isContentEditable);
}

function showToast(message, tone = "ok") {
  if (!el.toastStack) return;
  const toast = document.createElement("div");
  toast.className = `wf-toast ${tone}`;
  toast.textContent = message;
  el.toastStack.appendChild(toast);
  window.setTimeout(() => {
    toast.remove();
  }, 3400);
}

function logEvent(message) {
  if (!el.eventLog) return;
  const now = new Date().toLocaleTimeString();
  const lines = el.eventLog.textContent ? el.eventLog.textContent.split("\n") : [];
  lines.push(`[${now}] ${message}`);
  el.eventLog.textContent = lines.slice(-MAX_LOG_LINES).join("\n");
  el.eventLog.scrollTop = el.eventLog.scrollHeight;
}

function clearLog() {
  if (!el.eventLog) return;
  el.eventLog.textContent = "";
  showToast(t("logCleared"), "ok");
}

function setSocketStatus(statusKey) {
  socketStateKey = statusKey;
  if (!el.socketStatusBadge) return;
  const clsMap = {
    socketConnecting: "wf-status-connecting",
    socketConnected: "wf-status-connected",
    socketDisconnected: "wf-status-disconnected",
    socketError: "wf-status-error",
  };
  el.socketStatusBadge.classList.remove(
    "wf-status-connecting",
    "wf-status-connected",
    "wf-status-disconnected",
    "wf-status-error",
  );
  el.socketStatusBadge.classList.add(clsMap[statusKey] || "wf-status-connecting");
  el.socketStatusBadge.textContent = t(statusKey);
}

function setRunSummary(text) {
  if (!el.runSummary) return;
  el.runSummary.textContent = text;
}

function clearDownloadLinks() {
  if (!el.downloadLinks) return;
  el.downloadLinks.innerHTML = "";
}

function renderDownloadLinks(rawUrl, optimizedUrl, rawName, optimizedName) {
  clearDownloadLinks();
  if (!el.downloadLinks) return;

  const fragment = document.createDocumentFragment();

  const rawLine = document.createElement("div");
  if (rawUrl) {
    const a = document.createElement("a");
    a.href = rawUrl;
    a.textContent = t("downloadRaw");
    a.title = rawName || t("downloadRaw");
    rawLine.appendChild(a);
  } else {
    rawLine.textContent = t("rawUnavailable");
  }
  fragment.appendChild(rawLine);

  const optLine = document.createElement("div");
  if (optimizedUrl) {
    const a = document.createElement("a");
    a.href = optimizedUrl;
    a.textContent = t("downloadOptimized");
    a.title = optimizedName || t("downloadOptimized");
    optLine.appendChild(a);
  } else {
    optLine.textContent = t("optimizedUnavailable");
  }
  fragment.appendChild(optLine);

  el.downloadLinks.appendChild(fragment);
}

function updateZoomBadge() {
  if (!graphCanvas || !el.zoomBadge) return;
  const scale = graphCanvas.ds && graphCanvas.ds.scale ? graphCanvas.ds.scale : 1;
  el.zoomBadge.textContent = tf("zoomLabel", { value: Math.round(scale * 100) });
}

function updateSelectedBadge() {
  if (!el.selectedNodeBadge) return;
  if (!selectedNode) {
    el.selectedNodeBadge.textContent = t("selectedNodeNone");
    return;
  }
  const title = selectedNode.title || selectedNode.type || selectedNode.id;
  el.selectedNodeBadge.textContent = tf("selectedNode", { name: `${title}` });
}

function formatIo(ioList) {
  if (!Array.isArray(ioList) || ioList.length === 0) return t("na");
  return ioList.map((io, idx) => `${idx}:${io.name || "-"} (${io.type || "any"})`).join(", ");
}

function renderInspector() {
  if (!el.inspectorEmpty || !el.nodeInspector) return;

  if (!selectedNode) {
    el.inspectorEmpty.hidden = false;
    el.nodeInspector.innerHTML = "";
    return;
  }

  el.inspectorEmpty.hidden = true;
  const rows = [
    [t("inspectorId"), String(selectedNode.id)],
    [t("inspectorType"), selectedNode.type || t("unknown")],
    [t("inspectorTitle"), selectedNode.title || t("unknown")],
    [t("inspectorPosition"), `${Math.round(selectedNode.pos[0])}, ${Math.round(selectedNode.pos[1])}`],
    [t("inspectorProperties"), JSON.stringify(selectedNode.properties || {}, null, 2)],
    [t("inspectorInputs"), formatIo(selectedNode.inputs)],
    [t("inspectorOutputs"), formatIo(selectedNode.outputs)],
  ];

  el.nodeInspector.innerHTML = "";
  rows.forEach(([name, value]) => {
    const dt = document.createElement("dt");
    dt.textContent = name;
    const dd = document.createElement("dd");
    dd.textContent = value;
    el.nodeInspector.appendChild(dt);
    el.nodeInspector.appendChild(dd);
  });
}

function applyTranslations() {
  document.title = t("pageTitle");

  if (el.brandTitle) el.brandTitle.textContent = t("brandTitle");
  if (el.brandSubtitle) el.brandSubtitle.textContent = t("brandSubtitle");
  if (el.roleLabel) el.roleLabel.textContent = t("roleLabel");
  if (el.langLabel) el.langLabel.textContent = t("langLabel");
  if (el.themeLabel) el.themeLabel.textContent = t("themeLabel");
  if (el.classicLink) el.classicLink.textContent = t("classicUi");

  if (el.roleSelect) {
    if (el.roleSelect.options[0]) el.roleSelect.options[0].textContent = t("roleObserver");
    if (el.roleSelect.options[1]) el.roleSelect.options[1].textContent = t("roleOperator");
    if (el.roleSelect.options[2]) el.roleSelect.options[2].textContent = t("roleBuilder");
  }
  if (el.langSelect) {
    if (el.langSelect.options[0]) el.langSelect.options[0].textContent = "한국어";
    if (el.langSelect.options[1]) el.langSelect.options[1].textContent = "English";
  }
  if (el.themeSelect) {
    if (el.themeSelect.options[0]) el.themeSelect.options[0].textContent = t("lightMode");
    if (el.themeSelect.options[1]) el.themeSelect.options[1].textContent = t("darkMode");
  }

  if (el.libraryPanelTitle) el.libraryPanelTitle.textContent = t("libraryPanelTitle");
  if (el.librarySearchLabel) el.librarySearchLabel.textContent = t("librarySearchLabel");
  if (el.librarySearchInput) el.librarySearchInput.placeholder = t("librarySearchPlaceholder");
  if (el.libraryCategoryLabel) el.libraryCategoryLabel.textContent = t("libraryCategoryLabel");
  if (el.uploadPanelTitle) el.uploadPanelTitle.textContent = t("uploadPanelTitle");
  if (el.uploadBatchBtn) el.uploadBatchBtn.textContent = t("uploadBatchBtn");
  if (el.applyUploadBtn) el.applyUploadBtn.textContent = t("applyUploadBtn");
  if (el.uploadSelectLabel) el.uploadSelectLabel.textContent = t("uploadSelectLabel");
  if (el.uploadHint) el.uploadHint.textContent = t("uploadHint");
  if (el.quickPanelTitle) el.quickPanelTitle.textContent = t("quickPanelTitle");
  if (el.seedGraphBtn) el.seedGraphBtn.textContent = t("seedGraphBtn");
  if (el.resetViewBtn) el.resetViewBtn.textContent = t("resetViewBtn");
  if (el.shortcutHint) el.shortcutHint.textContent = t("shortcutHint");
  if (el.runPanelTitle) el.runPanelTitle.textContent = t("runPanelTitle");
  if (el.runGraphBtn) el.runGraphBtn.textContent = t("runGraphBtn");
  if (el.clearLogBtn) el.clearLogBtn.textContent = t("clearLogBtn");
  if (el.inspectorPanelTitle) el.inspectorPanelTitle.textContent = t("inspectorPanelTitle");
  if (el.inspectorEmpty) el.inspectorEmpty.textContent = t("inspectorEmpty");
  if (el.eventsPanelTitle) el.eventsPanelTitle.textContent = t("eventsPanelTitle");

  setSocketStatus(socketStateKey);
  updateRolePermissionHint();
  updateSelectedBadge();
  updateZoomBadge();
  applyCanvasTheme();
  renderLibrary();
  renderInspector();

  if (el.downloadLinks && el.downloadLinks.dataset.ready === "1") {
    renderDownloadLinks(
      el.downloadLinks.dataset.rawUrl || "",
      el.downloadLinks.dataset.optimizedUrl || "",
      el.downloadLinks.dataset.rawName || "",
      el.downloadLinks.dataset.optimizedName || "",
    );
  }
}

function updateRolePermissionHint() {
  if (!el.permissionHint) return;
  const permissionKey = currentPermissions().permissionKey;
  el.permissionHint.textContent = t(permissionKey);
}

function applyRoleState() {
  if (el.roleSelect) {
    el.roleSelect.value = role;
  }

  const permissions = currentPermissions();

  if (el.runGraphBtn) el.runGraphBtn.disabled = !permissions.canRun;
  if (el.nodeFiles) el.nodeFiles.disabled = !permissions.canUpload;
  if (el.uploadBatchBtn) el.uploadBatchBtn.disabled = !permissions.canUpload;
  if (el.applyUploadBtn) el.applyUploadBtn.disabled = !permissions.canUpload;
  if (el.seedGraphBtn) el.seedGraphBtn.disabled = !permissions.canSeed;

  if (graphCanvas) {
    graphCanvas.read_only = !permissions.canEdit;
    graphCanvas.allow_dragnodes = permissions.canEdit;
    graphCanvas.allow_interaction = true;
    graphCanvas.allow_searchbox = permissions.canEdit;
    graphCanvas.setDirty(true, true);
  }

  updateRolePermissionHint();
  renderLibrary();
}

function nodeCategoryLabel(category) {
  return t(`cat_${category}`) || category || t("unknown");
}

function populateCategorySelect(list) {
  if (!el.libraryCategorySelect) return;
  const previous = el.libraryCategorySelect.value || "all";
  const categories = Array.from(new Set((list || []).map((item) => item.category).filter(Boolean))).sort();

  el.libraryCategorySelect.innerHTML = "";
  const allOption = document.createElement("option");
  allOption.value = "all";
  allOption.textContent = t("libraryAllCategories");
  el.libraryCategorySelect.appendChild(allOption);

  categories.forEach((cat) => {
    const opt = document.createElement("option");
    opt.value = cat;
    opt.textContent = nodeCategoryLabel(cat);
    el.libraryCategorySelect.appendChild(opt);
  });

  if ([...el.libraryCategorySelect.options].some((opt) => opt.value === previous)) {
    el.libraryCategorySelect.value = previous;
  }
}

function getFilteredLibrary() {
  const q = (el.librarySearchInput ? el.librarySearchInput.value : "").trim().toLowerCase();
  const selectedCategory = el.libraryCategorySelect ? el.libraryCategorySelect.value : "all";

  return lastLibrary.filter((item) => {
    if (selectedCategory !== "all" && item.category !== selectedCategory) return false;
    if (!q) return true;
    const haystack = `${item.title || ""} ${item.type || ""} ${item.category || ""}`.toLowerCase();
    return haystack.includes(q);
  });
}

function getCanvasCenterGraphSpace() {
  if (!graphCanvas) return { x: 80, y: 80 };
  const ds = graphCanvas.ds || { scale: 1, offset: [0, 0] };
  const w = graphCanvas.canvas ? graphCanvas.canvas.width : el.graphCanvas.clientWidth;
  const h = graphCanvas.canvas ? graphCanvas.canvas.height : el.graphCanvas.clientHeight;
  return {
    x: (w * 0.5 - ds.offset[0]) / ds.scale,
    y: (h * 0.5 - ds.offset[1]) / ds.scale,
  };
}

function setWidgetValue(node, widgetName, value) {
  if (!node || !Array.isArray(node.widgets)) return;
  const widget = node.widgets.find((item) => item && item.name === widgetName);
  if (!widget) return;
  widget.value = value;
  if (typeof widget.callback === "function") {
    widget.callback(value);
  }
}

function addNodeFromLibrary(nodeType) {
  if (!graph) return;
  if (!currentPermissions().canEdit) {
    showToast(t("deniedEdit"), "warn");
    return;
  }
  const node = LiteGraph.createNode(nodeType);
  if (!node) {
    showToast(`${t("unknown")}: ${nodeType}`, "error");
    return;
  }

  const center = getCanvasCenterGraphSpace();
  node.pos = [center.x - 120 + Math.random() * 24, center.y - 70 + Math.random() * 24];
  graph.add(node);

  if (selectedUploadId && node.type === "data/upload_ref") {
    node.properties.upload_id = selectedUploadId;
    setWidgetValue(node, "upload_id", selectedUploadId);
  }
  if (selectedUploadId && node.type === "workflow/run_pipeline") {
    node.properties.upload_id = selectedUploadId;
    setWidgetValue(node, "fallback_upload", selectedUploadId);
  }

  selectedNode = node;
  graphCanvas.selectNode(node);
  renderInspector();
  updateSelectedBadge();
  graphCanvas.setDirty(true, true);
}

function renderLibrary() {
  if (!el.libraryList) return;
  const filtered = getFilteredLibrary();
  el.libraryList.innerHTML = "";
  if (el.libraryCountBadge) el.libraryCountBadge.textContent = String(filtered.length);

  if (!filtered.length) {
    const li = document.createElement("li");
    li.textContent = t("libraryEmpty");
    el.libraryList.appendChild(li);
    return;
  }

  filtered.forEach((item) => {
    const li = document.createElement("li");
    li.dataset.type = item.type || "";

    const rowTop = document.createElement("div");
    rowTop.className = "wf-library-row";
    const title = document.createElement("strong");
    title.textContent = item.title || item.type || t("unknown");
    const cat = document.createElement("span");
    cat.className = "wf-library-meta";
    cat.textContent = nodeCategoryLabel(item.category);
    rowTop.appendChild(title);
    rowTop.appendChild(cat);

    const rowBottom = document.createElement("div");
    rowBottom.className = "wf-library-row";
    const typeMeta = document.createElement("span");
    typeMeta.className = "wf-library-meta";
    typeMeta.textContent = item.type || t("unknown");
    rowBottom.appendChild(typeMeta);

    const addBtn = document.createElement("button");
    addBtn.className = "wf-mini-btn";
    addBtn.type = "button";
    addBtn.textContent = t("addNode");
    addBtn.disabled = !currentPermissions().canEdit;
    addBtn.addEventListener("click", () => addNodeFromLibrary(item.type));
    rowBottom.appendChild(addBtn);

    li.appendChild(rowTop);
    li.appendChild(rowBottom);
    li.addEventListener("dblclick", () => addNodeFromLibrary(item.type));
    el.libraryList.appendChild(li);
  });
}

function populateLibrary(list) {
  lastLibrary = Array.isArray(list) ? list : [];
  populateCategorySelect(lastLibrary);
  renderLibrary();
}

function resizeCanvas() {
  if (!el.graphCanvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = el.graphCanvas.getBoundingClientRect();
  el.graphCanvas.width = Math.max(1, Math.floor(rect.width * dpr));
  el.graphCanvas.height = Math.max(1, Math.floor(rect.height * dpr));
  if (graphCanvas) {
    graphCanvas.resize();
    graphCanvas.setDirty(true, true);
    updateZoomBadge();
  }
}

function setZoom(nextScale) {
  if (!graphCanvas) return;
  const scale = Math.max(0.2, Math.min(3.2, nextScale));
  if (typeof graphCanvas.setZoom === "function") {
    const center = [graphCanvas.canvas.width * 0.5, graphCanvas.canvas.height * 0.5];
    graphCanvas.setZoom(scale, center);
  } else if (graphCanvas.ds) {
    graphCanvas.ds.scale = scale;
  }
  graphCanvas.setDirty(true, true);
  updateZoomBadge();
}

function zoomIn() {
  if (!graphCanvas) return;
  setZoom((graphCanvas.ds ? graphCanvas.ds.scale : 1) * 1.12);
}

function zoomOut() {
  if (!graphCanvas) return;
  setZoom((graphCanvas.ds ? graphCanvas.ds.scale : 1) / 1.12);
}

function resetView() {
  if (!graphCanvas) return;
  if (graphCanvas.ds) {
    graphCanvas.ds.scale = 1;
    graphCanvas.ds.offset[0] = 20;
    graphCanvas.ds.offset[1] = 20;
  }
  graphCanvas.setDirty(true, true);
  updateZoomBadge();
  showToast(t("viewReset"), "ok");
}

function fitGraphView() {
  if (!graphCanvas || !graph) return;
  const bounds = typeof graph.getBounding === "function" ? graph.getBounding() : null;
  if (!bounds || !bounds[2] || !bounds[3]) {
    resetView();
    return;
  }

  const canvasW = graphCanvas.canvas.width;
  const canvasH = graphCanvas.canvas.height;
  const padding = 120;
  const boundW = Math.max(1, bounds[2]);
  const boundH = Math.max(1, bounds[3]);
  const scaleX = (canvasW - padding) / boundW;
  const scaleY = (canvasH - padding) / boundH;
  const scale = Math.max(0.2, Math.min(2.8, Math.min(scaleX, scaleY)));

  graphCanvas.ds.scale = scale;
  graphCanvas.ds.offset[0] = -bounds[0] * scale + (canvasW - boundW * scale) * 0.5;
  graphCanvas.ds.offset[1] = -bounds[1] * scale + (canvasH - boundH * scale) * 0.5;
  graphCanvas.setDirty(true, true);
  updateZoomBadge();
  showToast(t("fitDone"), "ok");
}

function centerSelectedNode() {
  if (!graphCanvas || !selectedNode) {
    showToast(t("centeredEmpty"), "warn");
    return;
  }
  const size = selectedNode.size || [160, 80];
  const canvasW = graphCanvas.canvas.width;
  const canvasH = graphCanvas.canvas.height;
  const scale = graphCanvas.ds.scale || 1;
  graphCanvas.ds.offset[0] = canvasW * 0.5 - (selectedNode.pos[0] + size[0] * 0.5) * scale;
  graphCanvas.ds.offset[1] = canvasH * 0.5 - (selectedNode.pos[1] + size[1] * 0.5) * scale;
  graphCanvas.setDirty(true, true);
  showToast(tf("centeredNode", { nodeId: selectedNode.id }), "ok");
}

function decorateCanvasColors() {
  if (!graphCanvas) return;
  graphCanvas.default_connection_color_byType = { ...TYPE_COLORS };
  graphCanvas.default_connection_color_byTypeOff = { ...TYPE_COLORS };
  if (LGraphCanvas && LGraphCanvas.link_type_colors) {
    Object.assign(LGraphCanvas.link_type_colors, TYPE_COLORS);
  }
}

function isLightTheme() {
  return (document.documentElement.getAttribute("data-theme") || "dark") === "light";
}

function applyCanvasTheme() {
  if (!graphCanvas) return;
  const light = isLightTheme();
  // Solid themed fill behind the nodes: white-ish in light, deep navy in dark.
  graphCanvas.background_image = null;
  graphCanvas.render_canvas_border = false;
  graphCanvas.clear_background = true;
  graphCanvas.clear_background_color = light ? "#f4f7fc" : "#0a0f1d";
  // Node chrome / link contrast that reads on both backgrounds.
  if (LGraphCanvas) {
    if (LGraphCanvas.node_title_color !== undefined) {
      LGraphCanvas.node_title_color = light ? "#1a2540" : "#e6eeff";
    }
    if (LGraphCanvas.link_color !== undefined) {
      LGraphCanvas.link_color = light ? "#6b7a99" : "#9fb0d0";
    }
  }
  graphCanvas.setDirty(true, true);
}

function registerNodeTypes() {
  if (nodeTypesRegistered) return;
  nodeTypesRegistered = true;

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

  // Display-only "stage" node: documents what the agent does inside RunPipeline.
  // It is never executed by the server (not flow-reachable, type ignored), it
  // exists purely to render the agent architecture as a diagram.
  function StageNode() {
    this.title = "Stage";
    this.color = "#1b2a4a";
    this.bgcolor = "#16223e";
    this.addInput("in", "stage");
    this.addOutput("out", "stage");
    this.properties = { step: "", desc: "", lane: "pipeline" };
    this.size = [200, 66];
  }
  StageNode.prototype.onDrawForeground = function (ctx) {
    if (this.flags && this.flags.collapsed) return;
    ctx.save();
    if (this.properties.step) {
      ctx.fillStyle = "rgba(123,150,255,0.9)";
      ctx.font = "bold 10px Inter, system-ui, sans-serif";
      ctx.fillText(String(this.properties.step), 10, 34);
    }
    ctx.fillStyle = "rgba(210,224,255,0.8)";
    ctx.font = "11px Inter, system-ui, sans-serif";
    const maxW = this.size[0] - 18;
    const words = String(this.properties.desc || "").split(" ");
    let line = "";
    let y = 50;
    for (const word of words) {
      const test = line ? `${line} ${word}` : word;
      if (ctx.measureText(test).width > maxW && line) {
        ctx.fillText(line, 10, y);
        y += 13;
        line = word;
        if (y > this.size[1] + 8) { line = ""; break; }
      } else {
        line = test;
      }
    }
    if (line) ctx.fillText(line, 10, y);
    ctx.restore();
  };
  LiteGraph.registerNodeType("display/stage", StageNode);
}

function setNodeVisualState(nodeId, state) {
  if (!graph) return;
  const node = graph.getNodeById(Number(nodeId));
  if (!node) return;
  if (state === "running") node.boxcolor = "#f59e0b";
  else if (state === "done") node.boxcolor = "#10b981";
  else if (state === "error") node.boxcolor = "#ef4444";
  else node.boxcolor = "#7c869a";
  graphCanvas.setDirty(true, true);
}

function applyUploadIdToNodes(uploadId) {
  if (!graph || !uploadId) return;
  graph._nodes
    .filter((node) => node.type === "data/upload_ref")
    .forEach((node) => {
      node.properties.upload_id = uploadId;
      setWidgetValue(node, "upload_id", uploadId);
    });

  graph._nodes
    .filter((node) => node.type === "workflow/run_pipeline")
    .forEach((node) => {
      node.properties.upload_id = uploadId;
      setWidgetValue(node, "fallback_upload", uploadId);
    });

  graphCanvas.setDirty(true, true);
}

function seedGraph(options = {}) {
  const bypassPermission = Boolean(options.bypassPermission);
  const silent = Boolean(options.silent);
  if (!graph) return;
  if (!bypassPermission && !currentPermissions().canSeed) {
    showToast(t("deniedSeed"), "warn");
    return;
  }

  graph.clear();
  selectedNode = null;

  // --- Executable backbone (this actually runs on the agent) ---------------
  const start = LiteGraph.createNode("workflow/start");
  const upload = LiteGraph.createNode("data/upload_ref");
  const runPipeline = LiteGraph.createNode("workflow/run_pipeline");
  const download = LiteGraph.createNode("workflow/download");

  start.pos = [40, 40];
  upload.pos = [40, 210];
  runPipeline.pos = [380, 70];
  download.pos = [740, 70];

  graph.add(start);
  graph.add(upload);
  graph.add(runPipeline);
  graph.add(download);

  start.connect(0, runPipeline, 0);
  start.connect(1, runPipeline, 1);
  upload.connect(0, runPipeline, 2);
  runPipeline.connect(0, download, 0);
  runPipeline.connect(1, download, 1);

  if (selectedUploadId) {
    upload.properties.upload_id = selectedUploadId;
    setWidgetValue(upload, "upload_id", selectedUploadId);
    runPipeline.properties.upload_id = selectedUploadId;
    setWidgetValue(runPipeline, "fallback_upload", selectedUploadId);
  }

  // --- Agent architecture diagram (display-only stage nodes) ---------------
  const lang = currentLang();
  const P = (en, ko) => (lang === "ko" ? ko : en);

  function makeStage(step, title, desc, x, y, color) {
    const node = LiteGraph.createNode("display/stage");
    node.title = title;
    node.properties.step = step;
    node.properties.desc = desc;
    node.pos = [x, y];
    if (color) {
      node.color = color;
      node.bgcolor = color;
    }
    graph.add(node);
    return node;
  }

  // What RunPipeline performs internally, in order.
  const pipeline = [
    ["01", P("Acquire", "획득"), P("Upload · EXIF · lens correction", "업로드 · EXIF · 렌즈보정")],
    ["02", P("Register", "정합"), P("LoFTR · SIFT · DINOv2 retrieval", "LoFTR · SIFT · DINOv2 검색")],
    ["03", P("Bundle Adjust", "번들조정"), P("Huber IRLS global BA", "Huber IRLS 전역 BA")],
    ["04", P("Blend", "블렌딩"), P("Tiled multi-band + gain", "타일 멀티밴드 + 게인")],
    ["05", P("Color", "컬러"), P("ColorChecker · ΔE2000 · FADGI", "컬러차트 · ΔE2000 · FADGI")],
    ["06", P("Quality", "품질"), P("Holes · sharpness · IQA", "구멍 · 선명도 · IQA")],
    ["07", P("Repair", "보강"), P("Inpaint (LaMa / Telea)", "인페인팅 (LaMa / Telea)")],
    ["08", P("Provenance", "출처"), P("Coverage · synthetic · uncertainty", "커버리지 · 합성 · 불확실도")],
    ["09", P("Export", "내보내기"), P("BigTIFF · JPEG · DZI", "BigTIFF · JPEG · DZI")],
    ["10", P("IIIF", "IIIF"), P("Image API 3.0 · manifest", "Image API 3.0 · 매니페스트")],
    ["11", P("Manifest", "매니페스트"), P("SHA-256 · Dublin Core", "SHA-256 · Dublin Core")],
  ];
  const laneHead = makeStage("▶", P("Agent Pipeline", "에이전트 파이프라인"),
    P("RunPipeline executes these stages", "RunPipeline 내부 단계"), 40, 360, "#3b2f6b");
  laneHead.size = [220, 60];

  const stageNodes = [];
  const COLS = 6;
  const STEP_X = 220;
  const ROW_Y = [440, 580];
  pipeline.forEach((s, i) => {
    const row = Math.floor(i / COLS);
    const col = i % COLS;
    const node = makeStage(s[0], s[1], s[2], 40 + col * STEP_X, ROW_Y[row]);
    stageNodes.push(node);
    if (i > 0) stageNodes[i - 1].connect(0, node, 0);
  });

  // Agent intelligence capabilities that branch off Export (on-demand actions).
  const intel = [
    [P("Condition AI", "조건분석"), P("Cracks · discolouration", "균열 · 변색")],
    [P("AI Restore", "AI복원"), P("De-colour / crack / noise", "변색·균열·노이즈")],
    [P("Image→3D", "이미지→3D"), P("Depth · Gaussian splat", "깊이 · 가우시안 스플랫")],
    [P("Multi-view 3D", "멀티뷰 3D"), P("Fused reconstruction", "융합 복원")],
    [P("Semantic", "의미검색"), P("CLIP tags · search", "CLIP 태그 · 검색")],
  ];
  const exportNode = stageNodes[8];
  intel.forEach((c, i) => {
    const node = makeStage("AI", c[0], c[1], 40 + i * STEP_X, 720, "#0f4c43");
    if (exportNode) exportNode.connect(0, node, 0);
  });

  graphCanvas.setDirty(true, true);
  fitGraphView();
  renderInspector();
  updateSelectedBadge();
  if (!silent) {
    logEvent(t("graphSeeded"));
    showToast(t("graphSeeded"), "ok");
  }
}

function hasNodeType(nodeType) {
  return Boolean(
    graph &&
      Array.isArray(graph._nodes) &&
      graph._nodes.some((node) => node && node.type === nodeType),
  );
}

function ensureRunnableGraphState() {
  if (!graph) return false;

  if (!selectedUploadId && el.uploadSelect && el.uploadSelect.value) {
    selectedUploadId = el.uploadSelect.value;
  }

  if (!selectedUploadId) {
    showToast(t("noUploads"), "warn");
    return false;
  }

  const needsDefaultGraph =
    !hasNodeType("workflow/start") ||
    !hasNodeType("data/upload_ref") ||
    !hasNodeType("workflow/run_pipeline") ||
    !hasNodeType("workflow/download");

  if (needsDefaultGraph) {
    seedGraph({ bypassPermission: true, silent: true });
    logEvent(t("autoRunGraphPrepared"));
    showToast(t("autoRunGraphPrepared"), "ok");
  }

  applyUploadIdToNodes(selectedUploadId);
  return true;
}

async function readErrorMessage(response) {
  const text = await response.text();
  if (!text) return `${response.status}`;
  try {
    const parsed = JSON.parse(text);
    return parsed.detail || parsed.message || text;
  } catch (_) {
    return text;
  }
}

async function uploadBatch() {
  if (!currentPermissions().canUpload) {
    showToast(t("deniedUpload"), "warn");
    return;
  }

  const files = el.nodeFiles && el.nodeFiles.files ? el.nodeFiles.files : null;
  if (!files || files.length < 2) {
    showToast(t("needTwoImages"), "warn");
    return;
  }

  const formData = new FormData();
  Array.from(files).forEach((file) => formData.append("files", file));

  const response = await fetch("/api/node/uploads", {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const msg = await readErrorMessage(response);
    throw new Error(tf("uploadFailed", { message: msg }));
  }

  const data = await response.json();
  selectedUploadId = data.upload_id;
  await refreshUploadList(data.upload_id);
  applyUploadIdToNodes(selectedUploadId);

  const line = tf("uploadCreated", { uploadId: data.upload_id, count: data.count });
  logEvent(line);
  showToast(line, "ok");
}

async function refreshUploadList(preferredUploadId) {
  if (!el.uploadSelect) return;
  const response = await fetch("/api/node/uploads");
  if (!response.ok) return;

  const data = await response.json();
  const uploads = Array.isArray(data.uploads) ? data.uploads : [];

  el.uploadSelect.innerHTML = "";
  if (!uploads.length) {
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = t("noUploads");
    el.uploadSelect.appendChild(emptyOption);
    selectedUploadId = "";
    return;
  }

  uploads.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.upload_id;
    option.textContent = `${item.upload_id} (${item.count})`;
    el.uploadSelect.appendChild(option);
  });

  if (preferredUploadId && uploads.some((item) => item.upload_id === preferredUploadId)) {
    el.uploadSelect.value = preferredUploadId;
  }
  selectedUploadId = el.uploadSelect.value;
}

function applySelectedUploadToNodes() {
  if (!currentPermissions().canUpload) {
    showToast(t("deniedUpload"), "warn");
    return;
  }
  selectedUploadId = el.uploadSelect ? el.uploadSelect.value : "";
  if (!selectedUploadId) {
    showToast(t("noUploads"), "warn");
    return;
  }
  applyUploadIdToNodes(selectedUploadId);
  const line = tf("uploadApplied", { uploadId: selectedUploadId });
  logEvent(line);
  showToast(line, "ok");
}

async function runGraph() {
  if (!currentPermissions().canRun) {
    showToast(t("deniedRun"), "warn");
    return;
  }
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    showToast(t("wsNotConnected"), "warn");
    return;
  }

  if (!selectedUploadId && el.nodeFiles && el.nodeFiles.files && el.nodeFiles.files.length >= 2) {
    try {
      await uploadBatch();
    } catch (err) {
      const msg = err && err.message ? err.message : String(err);
      logEvent(msg);
      showToast(msg, "error");
      return;
    }
  }

  if (!ensureRunnableGraphState()) {
    return;
  }

  setRunSummary(t("runRequested"));
  clearDownloadLinks();
  if (el.downloadLinks) {
    el.downloadLinks.dataset.ready = "0";
    delete el.downloadLinks.dataset.rawUrl;
    delete el.downloadLinks.dataset.optimizedUrl;
    delete el.downloadLinks.dataset.rawName;
    delete el.downloadLinks.dataset.optimizedName;
  }
  ws.send(JSON.stringify({ action: "run_graph", graph: graph.serialize() }));
  logEvent(t("runRequested"));
}

function startPing() {
  stopPing();
  pingTimer = window.setInterval(() => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ action: "ping", ts: Date.now() }));
  }, 15000);
}

function stopPing() {
  if (pingTimer) {
    window.clearInterval(pingTimer);
    pingTimer = null;
  }
}

function scheduleReconnect() {
  if (wsReconnectTimer) return;
  wsReconnectTimer = window.setTimeout(() => {
    wsReconnectTimer = null;
    connectSocket();
  }, reconnectDelay);
  reconnectDelay = Math.min(5000, reconnectDelay + 600);
}

function connectSocket() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${scheme}://${window.location.host}/ws/workflow`);
  setSocketStatus("socketConnecting");

  ws.onopen = () => {
    reconnectDelay = SOCKET_RECONNECT_BASE_MS;
    setSocketStatus("socketConnected");
    logEvent(t("wsConnectedLog"));
    startPing();
    ws.send(JSON.stringify({ action: "get_library" }));
  };

  ws.onmessage = (evt) => {
    let message = null;
    try {
      message = JSON.parse(evt.data);
    } catch (_) {
      return;
    }
    const event = message.event;
    const payload = message.payload || {};

    if (event === "hello" || event === "library") {
      Object.assign(TYPE_COLORS, payload.type_colors || {});
      decorateCanvasColors();
      populateLibrary(payload.node_library || []);
      return;
    }

    if (event === "node_state") {
      setNodeVisualState(payload.node_id, payload.state);
      if (payload.message) {
        logEvent(`node ${payload.node_id}: ${payload.message}`);
      }
      return;
    }

    if (event === "session_created") {
      const sessionName = payload.session_name || t("unknown");
      const uploadId = payload.upload_id || t("na");
      const line = tf("sessionCreated", { name: sessionName, uploadId });
      setRunSummary(line);
      logEvent(line);
      return;
    }

    if (event === "package_ready") {
      const rawUrl = payload.raw_download_url || payload.download_url || "";
      const optimizedUrl = payload.optimized_download_url || "";
      const rawName = payload.raw_filename || payload.filename || "";
      const optimizedName = payload.optimized_filename || "";

      renderDownloadLinks(rawUrl, optimizedUrl, rawName, optimizedName);
      if (el.downloadLinks) {
        el.downloadLinks.dataset.ready = "1";
        el.downloadLinks.dataset.rawUrl = rawUrl;
        el.downloadLinks.dataset.optimizedUrl = optimizedUrl;
        el.downloadLinks.dataset.rawName = rawName;
        el.downloadLinks.dataset.optimizedName = optimizedName;
      }

      setRunSummary(t("downloadReady"));
      logEvent(`${t("downloadReady")} raw=${rawUrl || t("na")} optimized=${optimizedUrl || t("na")}`);
      showToast(t("downloadReady"), "ok");
      return;
    }

    if (event === "run_started") {
      setRunSummary(t("runStarted"));
      logEvent(t("runStarted"));
      return;
    }

    if (event === "run_complete") {
      runCount += 1;
      setRunSummary(`${t("runCompleted")} #${runCount}`);
      logEvent(t("runCompleted"));
      return;
    }

    if (event === "run_failed") {
      const msg = payload.message || t("unknownError");
      const line = tf("runFailed", { message: msg });
      setRunSummary(line);
      logEvent(line);
      showToast(line, "error");
      return;
    }

    if (event === "flow_started") {
      logEvent(`flow started: ${payload.flow_name || t("unknown")}`);
      return;
    }

    if (event === "flow_finished") {
      logEvent(`flow finished: ${payload.flow_name || t("unknown")}`);
      return;
    }

    if (event === "error") {
      const line = payload.message || t("unknown");
      logEvent(`error: ${line}`);
      showToast(line, "error");
    }
  };

  ws.onclose = () => {
    stopPing();
    setSocketStatus("socketDisconnected");
    logEvent(t("wsDisconnectedLog"));
    scheduleReconnect();
  };

  ws.onerror = () => {
    setSocketStatus("socketError");
    logEvent(t("wsErrorLog"));
  };
}

function handleGlobalShortcuts(event) {
  if (event.defaultPrevented) return;
  const key = (event.key || "").toLowerCase();
  const ctrlOrMeta = event.ctrlKey || event.metaKey;

  if (ctrlOrMeta && key === "enter") {
    event.preventDefault();
    runGraph();
    return;
  }

  if (ctrlOrMeta && key === "k") {
    event.preventDefault();
    if (el.librarySearchInput) {
      el.librarySearchInput.focus();
      el.librarySearchInput.select();
    }
    return;
  }

  if (!ctrlOrMeta && !event.altKey && !event.shiftKey && key === "f" && !isTypingContext(event.target)) {
    event.preventDefault();
    fitGraphView();
    return;
  }

  if (!ctrlOrMeta && !event.altKey && event.shiftKey && key === "s" && !isTypingContext(event.target)) {
    event.preventDefault();
    seedGraph();
  }
}

function initGraph() {
  registerNodeTypes();
  graph = new LGraph();
  graphCanvas = new LGraphCanvas(el.graphCanvas, graph);
  applyCanvasTheme();

  graphCanvas.onNodeSelected = (node) => {
    selectedNode = node || null;
    updateSelectedBadge();
    renderInspector();
  };

  graphCanvas.onNodeDeselected = () => {
    selectedNode = null;
    updateSelectedBadge();
    renderInspector();
  };

  graph.start();
  decorateCanvasColors();
  resizeCanvas();
  updateZoomBadge();
  updateSelectedBadge();
  renderInspector();
}

function bindEvents() {
  if (el.roleSelect) {
    el.roleSelect.addEventListener("change", () => {
      const next = el.roleSelect.value;
      if (!ROLE_CONFIG[next]) return;
      role = next;
      saveRole(role);
      applyRoleState();
      const line = tf("roleSaved", { role: readRoleLabel(role) });
      logEvent(line);
      showToast(line, "ok");
    });
  }

  if (el.librarySearchInput) el.librarySearchInput.addEventListener("input", renderLibrary);
  if (el.libraryCategorySelect) el.libraryCategorySelect.addEventListener("change", renderLibrary);

  if (el.uploadBatchBtn) {
    el.uploadBatchBtn.addEventListener("click", async () => {
      try {
        await uploadBatch();
      } catch (err) {
        const msg = err && err.message ? err.message : String(err);
        logEvent(msg);
        showToast(msg, "error");
      }
    });
  }

  if (el.uploadSelect) {
    el.uploadSelect.addEventListener("change", () => {
      selectedUploadId = el.uploadSelect.value;
    });
  }
  if (el.applyUploadBtn) el.applyUploadBtn.addEventListener("click", applySelectedUploadToNodes);

  if (el.runGraphBtn) el.runGraphBtn.addEventListener("click", () => {
    runGraph();
  });
  if (el.seedGraphBtn) el.seedGraphBtn.addEventListener("click", () => seedGraph());
  if (el.resetViewBtn) el.resetViewBtn.addEventListener("click", resetView);
  if (el.clearLogBtn) el.clearLogBtn.addEventListener("click", clearLog);

  if (el.zoomInBtn) el.zoomInBtn.addEventListener("click", zoomIn);
  if (el.zoomOutBtn) el.zoomOutBtn.addEventListener("click", zoomOut);
  if (el.zoomFitBtn) el.zoomFitBtn.addEventListener("click", fitGraphView);
  if (el.centerNodeBtn) el.centerNodeBtn.addEventListener("click", centerSelectedNode);

  window.addEventListener("resize", resizeCanvas);
  window.addEventListener("keydown", handleGlobalShortcuts);

  if (window.ResizeObserver && el.graphCanvas && el.graphCanvas.parentElement) {
    const observer = new ResizeObserver(() => resizeCanvas());
    observer.observe(el.graphCanvas.parentElement);
  }
}

function initPreferences() {
  if (!window.UI_PREFS) {
    applyTranslations();
    return;
  }

  window.UI_PREFS.bindSelectors({
    languageSelectorId: "langSelect",
    themeSelectorId: "themeSelect",
  });
  window.UI_PREFS.onChange(() => {
    applyTranslations();
  });
}

async function bootstrap() {
  initGraph();
  seedGraph({ bypassPermission: true, silent: true });
  bindEvents();
  initPreferences();
  applyRoleState();
  applyTranslations();
  setRunSummary(t("runIdle"));
  connectSocket();

  try {
    await refreshUploadList();
    if (selectedUploadId) {
      applyUploadIdToNodes(selectedUploadId);
    }
  } catch (_) {
    // Ignore upload list fetch errors during initial boot.
  }
}

bootstrap();
