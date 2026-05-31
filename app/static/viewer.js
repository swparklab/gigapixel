const sessionId = window.__SESSION_ID__;
const metaEl = document.getElementById("meta");
const titleEl = document.getElementById("sessionHeading");
const annListEl = document.getElementById("annList");
const annTextEl = document.getElementById("annText");
const saveAnnBtn = document.getElementById("saveAnnBtn");
const refreshBtn = document.getElementById("refreshBtn");
const downloadRawBtn = document.getElementById("downloadRawBtn");
const downloadOptimizedBtn = document.getElementById("downloadOptimizedBtn");
const newSessionBtn = document.getElementById("newSessionBtn");
const langSelectEl = document.getElementById("langSelect");
const themeSelectEl = document.getElementById("themeSelect");
const langLabelEl = document.getElementById("langLabel");
const themeLabelEl = document.getElementById("themeLabel");
const annotationHeadingEl = document.getElementById("annotationHeading");
const annotationGuideEl = document.getElementById("annotationGuide");

let viewer = null;
let pendingPoint = null;
let currentSession = null;
let currentSessionStatus = "unknown";

const i18n = {
  en: {
    pageTitle: "Session Viewer",
    sessionHeading: "Session",
    annotationHeading: "Annotation",
    annotationGuide: "Click in viewer to pick coordinates, then write your note.",
    annotationPlaceholder: "annotation text",
    saveButton: "Save",
    refreshButton: "Refresh Status",
    downloadRawButton: "Download Raw High-Res",
    downloadOptimizedButton: "Download Optimized",
    newSessionButton: "New Session",
    langLabel: "Language",
    themeLabel: "Theme",
    lightMode: "Light",
    darkMode: "Night",
    statusMeta: "Status: {status} | Images: {count}",
    statusWaiting: "Status: {status} (refresh when processing finishes)",
    clickMeta: "Clicked: x={x}, y={y}",
    sessionFetchError: "Unable to load session info.",
    dziFetchError: "DZI is not ready yet. Please try again after processing.",
    invalidDzi: "Invalid DZI format.",
    annotationLoadFailed: "Failed to load annotations",
    deleteLabel: "Delete",
    clickFirstAlert: "Click a location in the viewer first.",
    annotationSaveFailed: "Failed to save annotation.",
    downloadNotReady: "Download is available only when the session is ready.",
    refreshError: "Error: {message}",
  },
  ko: {
    pageTitle: "세션 뷰어",
    sessionHeading: "세션",
    annotationHeading: "주석",
    annotationGuide: "뷰어를 클릭해 좌표를 선택한 뒤 주석을 입력하세요.",
    annotationPlaceholder: "주석 내용",
    saveButton: "저장",
    refreshButton: "상태 새로고침",
    downloadRawButton: "원본 고해상도 다운로드",
    downloadOptimizedButton: "최적화 버전 다운로드",
    newSessionButton: "새 세션 만들기",
    langLabel: "언어",
    themeLabel: "테마",
    lightMode: "밝은 모드",
    darkMode: "밤 모드",
    statusMeta: "상태: {status} | 이미지: {count}장",
    statusWaiting: "상태: {status} (처리 완료 후 새로고침하세요)",
    clickMeta: "선택 좌표: x={x}, y={y}",
    sessionFetchError: "세션 정보를 불러오지 못했습니다.",
    dziFetchError: "DZI가 아직 준비되지 않았습니다. 처리 완료 후 다시 시도하세요.",
    invalidDzi: "DZI 형식이 올바르지 않습니다.",
    annotationLoadFailed: "주석 로딩 실패",
    deleteLabel: "삭제",
    clickFirstAlert: "먼저 뷰어에서 위치를 클릭하세요.",
    annotationSaveFailed: "주석 저장 실패",
    downloadNotReady: "세션 준비 완료 후 다운로드할 수 있습니다.",
    refreshError: "오류: {message}",
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
  titleEl.textContent = currentSession && currentSession.name ? currentSession.name : t("sessionHeading");
  annotationHeadingEl.textContent = t("annotationHeading");
  annotationGuideEl.textContent = t("annotationGuide");
  annTextEl.placeholder = t("annotationPlaceholder");
  saveAnnBtn.textContent = t("saveButton");
  refreshBtn.textContent = t("refreshButton");
  downloadRawBtn.textContent = t("downloadRawButton");
  downloadOptimizedBtn.textContent = t("downloadOptimizedButton");
  newSessionBtn.textContent = t("newSessionButton");
  langLabelEl.textContent = t("langLabel");
  themeLabelEl.textContent = t("themeLabel");
  if (langSelectEl) {
    langSelectEl.options[0].textContent = "한국어";
    langSelectEl.options[1].textContent = "English";
  }
  if (themeSelectEl) {
    themeSelectEl.options[0].textContent = t("lightMode");
    themeSelectEl.options[1].textContent = t("darkMode");
  }
  if (currentSession) {
    if (currentSession.status === "ready") {
      setMeta(tf("statusMeta", { status: currentSession.status, count: currentSession.image_count }));
    } else {
      setMeta(tf("statusWaiting", { status: currentSession.status }));
    }
  }
}

function setMeta(text) {
  metaEl.textContent = text;
}

async function getSession() {
  const res = await fetch(`/api/sessions/${sessionId}`);
  if (!res.ok) throw new Error(t("sessionFetchError"));
  return res.json();
}

async function fetchDziXml() {
  const res = await fetch(`/api/sessions/${sessionId}/dzi`);
  if (!res.ok) throw new Error(t("dziFetchError"));
  return res.text();
}

function parseDzi(xmlText) {
  const doc = new DOMParser().parseFromString(xmlText, "application/xml");
  const image = doc.getElementsByTagNameNS("*", "Image")[0];
  const size = doc.getElementsByTagNameNS("*", "Size")[0];
  if (!image || !size) throw new Error(t("invalidDzi"));

  return {
    xmlns: image.getAttribute("xmlns") || "http://schemas.microsoft.com/deepzoom/2008",
    url: `/api/sessions/${sessionId}/tiles/`,
    format: image.getAttribute("Format") || "jpg",
    overlap: Number(image.getAttribute("Overlap") || "1"),
    tileSize: Number(image.getAttribute("TileSize") || "256"),
    width: Number(size.getAttribute("Width") || "1"),
    height: Number(size.getAttribute("Height") || "1"),
  };
}

function createMarker(annotation) {
  const el = document.createElement("div");
  el.className = "annotation-marker";
  el.title = annotation.text;
  el.style.width = "14px";
  el.style.height = "14px";
  el.style.background = "#e53935";
  el.style.border = "2px solid #fff";
  el.style.borderRadius = "50%";
  el.style.boxShadow = "0 2px 8px rgba(0,0,0,0.4)";
  const viewportPoint = viewer.viewport.imageToViewportCoordinates(annotation.x, annotation.y);
  viewer.addOverlay({
    element: el,
    location: viewportPoint,
    placement: OpenSeadragon.Placement.CENTER,
  });
}

async function loadAnnotations() {
  const res = await fetch(`/api/sessions/${sessionId}/annotations`);
  if (!res.ok) throw new Error(t("annotationLoadFailed"));
  const rows = await res.json();

  annListEl.innerHTML = "";
  for (const row of rows) {
    const li = document.createElement("li");
    li.textContent = `(${row.x.toFixed(2)}, ${row.y.toFixed(2)}) ${row.text}`;

    const delBtn = document.createElement("button");
    delBtn.textContent = t("deleteLabel");
    delBtn.style.marginTop = "8px";
    delBtn.addEventListener("click", async () => {
      await fetch(`/api/annotations/${row.id}`, { method: "DELETE" });
      await refreshViewer();
    });

    li.appendChild(delBtn);
    annListEl.appendChild(li);
    createMarker(row);
  }
}

async function addAnnotation() {
  const text = annTextEl.value.trim();
  if (!text) return;
  if (!pendingPoint) {
    alert(t("clickFirstAlert"));
    return;
  }

  const res = await fetch(`/api/sessions/${sessionId}/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x: pendingPoint.x, y: pendingPoint.y, text }),
  });

  if (!res.ok) {
    alert(t("annotationSaveFailed"));
    return;
  }

  annTextEl.value = "";
  pendingPoint = null;
  await refreshViewer();
}

async function initViewer() {
  const session = await getSession();
  currentSession = session;
  currentSessionStatus = session.status;
  titleEl.textContent = session.name || t("sessionHeading");
  setMeta(tf("statusMeta", { status: session.status, count: session.image_count }));
  downloadRawBtn.disabled = session.status !== "ready";
  downloadOptimizedBtn.disabled = session.status !== "ready";

  if (session.status !== "ready") {
    setMeta(tf("statusWaiting", { status: session.status }));
    return;
  }

  const dziXml = await fetchDziXml();
  const dzi = parseDzi(dziXml);

  viewer = OpenSeadragon({
    id: "openseadragon",
    prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/5.0.1/images/",
    tileSources: {
      Image: {
        xmlns: dzi.xmlns,
        Url: dzi.url,
        Format: dzi.format,
        Overlap: dzi.overlap,
        TileSize: dzi.tileSize,
        Size: {
          Width: dzi.width,
          Height: dzi.height,
        },
      },
    },
  });

  viewer.addHandler("canvas-click", (evt) => {
    const webPoint = evt.position;
    const viewportPoint = viewer.viewport.pointFromPixel(webPoint);
    const imagePoint = viewer.viewport.viewportToImageCoordinates(viewportPoint);
    pendingPoint = { x: imagePoint.x, y: imagePoint.y };
    setMeta(tf("clickMeta", { x: imagePoint.x.toFixed(1), y: imagePoint.y.toFixed(1) }));
  });

  await loadAnnotations();
}

function downloadRaw() {
  if (currentSessionStatus !== "ready") {
    alert(t("downloadNotReady"));
    return;
  }
  window.location.href = `/api/sessions/${sessionId}/download/raw`;
}

function downloadOptimized() {
  if (currentSessionStatus !== "ready") {
    alert(t("downloadNotReady"));
    return;
  }
  window.location.href = `/api/sessions/${sessionId}/download/optimized`;
}

function goToNewSession() {
  window.location.href = "/classic";
}

async function refreshViewer() {
  if (viewer) {
    viewer.destroy();
    viewer = null;
  }
  await initViewer();
}

refreshBtn.addEventListener("click", refreshViewer);
saveAnnBtn.addEventListener("click", addAnnotation);
downloadRawBtn.addEventListener("click", downloadRaw);
downloadOptimizedBtn.addEventListener("click", downloadOptimized);
newSessionBtn.addEventListener("click", goToNewSession);

if (window.UI_PREFS) {
  window.UI_PREFS.bindSelectors({
    languageSelectorId: "langSelect",
    themeSelectorId: "themeSelect",
  });
  window.UI_PREFS.onChange(() => applyTranslations());
} else {
  applyTranslations();
}

refreshViewer().catch((err) => {
  setMeta(tf("refreshError", { message: err.message }));
});
