const sessionId = window.__SESSION_ID__;

const titleEl = document.getElementById("sessionHeading");
const metaEl = document.getElementById("meta");
const statusBadgeEl = document.getElementById("statusBadge");
const imageCountBadgeEl = document.getElementById("imageCountBadge");
const annListEl = document.getElementById("annList");
const annTextEl = document.getElementById("annText");
const pendingPointEl = document.getElementById("pendingPoint");

const saveAnnBtn = document.getElementById("saveAnnBtn");
const refreshBtn = document.getElementById("refreshBtn");
const reloadAnnBtn = document.getElementById("reloadAnnBtn");
const downloadRawBtn = document.getElementById("downloadRawBtn");
const downloadOptimizedBtn = document.getElementById("downloadOptimizedBtn");
const newSessionBtn = document.getElementById("newSessionBtn");

const zoomInBtn = document.getElementById("zoomInBtn");
const zoomOutBtn = document.getElementById("zoomOutBtn");
const homeViewBtn = document.getElementById("homeViewBtn");
const fullPageBtn = document.getElementById("fullPageBtn");

const langSelectEl = document.getElementById("langSelect");
const themeSelectEl = document.getElementById("themeSelect");
const langLabelEl = document.getElementById("langLabel");
const themeLabelEl = document.getElementById("themeLabel");
const annotationHeadingEl = document.getElementById("annotationHeading");
const annotationGuideEl = document.getElementById("annotationGuide");
const annotationListHeadingEl = document.getElementById("annotationListHeading");
const downloadHeadingEl = document.getElementById("downloadHeading");
const viewerTitleEl = document.getElementById("viewerTitle");
const viewerSubtitleEl = document.getElementById("viewerSubtitle");
const viewerTipEl = document.getElementById("viewerTip");
const goClassicLinkEl = document.getElementById("goClassicLink");
const goWorkflowLinkEl = document.getElementById("goWorkflowLink");

let viewer = null;
let pendingPoint = null;
let currentSession = null;
let currentSessionStatus = "unknown";
let annotationCount = 0;

const i18n = {
  en: {
    pageTitle: "Session Viewer",
    viewerTitle: "Session Viewer",
    viewerSubtitle: "High-resolution image explorer with live annotations",
    viewerTip: "Mouse wheel zoom, drag to pan, click to pick point",
    sessionHeading: "Session",
    downloadHeading: "Downloads",
    annotationHeading: "Annotation",
    annotationListHeading: "Annotation List",
    annotationListWithCount: "Annotation List ({count})",
    annotationGuide: "Click in viewer to pick coordinates, then write your note.",
    annotationPlaceholder: "annotation text",
    pendingPointEmpty: "No point selected",
    pendingPointValue: "Selected point: x={x}, y={y}",
    saveButton: "Save",
    reloadButton: "Reload",
    refreshButton: "Refresh Status",
    downloadRawButton: "Download Raw BigTIFF",
    downloadOptimizedButton: "Download Optimized",
    newSessionButton: "New Session",
    zoomInButton: "+",
    zoomOutButton: "-",
    fitButton: "Fit",
    fullScreenButton: "Fullscreen",
    classicMode: "Classic Mode",
    expertMode: "Expert Mode",
    langLabel: "Language",
    themeLabel: "Theme",
    lightMode: "Light",
    darkMode: "Night",
    statusMeta: "Status: {status} | Images: {count}",
    statusWaiting: "Status: {status} (refresh when processing finishes)",
    imageCountLabel: "{count} images",
    sessionFetchError: "Unable to load session info.",
    dziFetchError: "DZI is not ready yet. Please try again after processing.",
    invalidDzi: "Invalid DZI format.",
    annotationLoadFailed: "Failed to load annotations",
    annotationEmpty: "No annotations yet.",
    deleteLabel: "Delete",
    clickFirstAlert: "Click a location in the viewer first.",
    annotationTextRequired: "Enter annotation text.",
    annotationSaveFailed: "Failed to save annotation.",
    downloadNotReady: "Download is available only when the session is ready.",
    refreshError: "Error: {message}",
    unknownError: "Unknown error",
  },
  ko: {
    pageTitle: "세션 뷰어",
    viewerTitle: "세션 뷰어",
    viewerSubtitle: "고해상도 이미지 열람과 실시간 주석 관리",
    viewerTip: "휠 확대/축소, 드래그 이동, 클릭 좌표 선택",
    sessionHeading: "세션",
    downloadHeading: "다운로드",
    annotationHeading: "주석",
    annotationListHeading: "주석 목록",
    annotationListWithCount: "주석 목록 ({count})",
    annotationGuide: "뷰어를 클릭해 좌표를 선택한 뒤 주석을 입력하세요.",
    annotationPlaceholder: "주석 내용",
    pendingPointEmpty: "선택된 좌표 없음",
    pendingPointValue: "선택 좌표: x={x}, y={y}",
    saveButton: "저장",
    reloadButton: "새로고침",
    refreshButton: "상태 새로고침",
    downloadRawButton: "원본 BigTIFF 다운로드",
    downloadOptimizedButton: "최적화 버전 다운로드",
    newSessionButton: "새 세션 만들기",
    zoomInButton: "+",
    zoomOutButton: "-",
    fitButton: "맞춤",
    fullScreenButton: "전체화면",
    classicMode: "클래식 모드",
    expertMode: "전문가 모드",
    langLabel: "언어",
    themeLabel: "테마",
    lightMode: "밝은 모드",
    darkMode: "밤 모드",
    statusMeta: "상태: {status} | 이미지: {count}",
    statusWaiting: "상태: {status} (처리 완료 후 새로고침하세요)",
    imageCountLabel: "이미지 {count}장",
    sessionFetchError: "세션 정보를 불러오지 못했습니다.",
    dziFetchError: "DZI가 아직 준비되지 않았습니다. 처리 완료 후 다시 시도하세요.",
    invalidDzi: "DZI 형식이 올바르지 않습니다.",
    annotationLoadFailed: "주석 로딩 실패",
    annotationEmpty: "아직 주석이 없습니다.",
    deleteLabel: "삭제",
    clickFirstAlert: "먼저 뷰어에서 위치를 클릭하세요.",
    annotationTextRequired: "주석 내용을 입력하세요.",
    annotationSaveFailed: "주석 저장 실패",
    downloadNotReady: "세션이 준비된 뒤에만 다운로드할 수 있습니다.",
    refreshError: "오류: {message}",
    unknownError: "알 수 없는 오류",
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

function setStatusBadge(status) {
  if (!statusBadgeEl) return;
  statusBadgeEl.textContent = status;
  statusBadgeEl.classList.remove("vwr-status-ready", "vwr-status-processing", "vwr-status-failed");
  if (status === "ready") {
    statusBadgeEl.classList.add("vwr-status-ready");
  } else if (status === "failed") {
    statusBadgeEl.classList.add("vwr-status-failed");
  } else {
    statusBadgeEl.classList.add("vwr-status-processing");
  }
}

function updatePendingPointText() {
  if (!pendingPointEl) return;
  if (!pendingPoint) {
    pendingPointEl.textContent = t("pendingPointEmpty");
    return;
  }
  pendingPointEl.textContent = tf("pendingPointValue", {
    x: pendingPoint.x.toFixed(1),
    y: pendingPoint.y.toFixed(1),
  });
}

function updateSaveButtonState() {
  const needsPoint = !pendingPoint;
  const needsText = !annTextEl.value.trim();
  saveAnnBtn.disabled = needsPoint || needsText;
  saveAnnBtn.title = needsPoint ? t("clickFirstAlert") : needsText ? t("annotationTextRequired") : "";
}

function updateMetaText() {
  if (!currentSession) return;
  if (currentSession.status === "ready") {
    metaEl.textContent = tf("statusMeta", {
      status: currentSession.status,
      count: currentSession.image_count,
    });
  } else {
    metaEl.textContent = tf("statusWaiting", { status: currentSession.status });
  }
}

function updateDownloadState() {
  const isReady = currentSessionStatus === "ready";
  downloadRawBtn.disabled = !isReady;
  downloadOptimizedBtn.disabled = !isReady;
  const disabledTitle = isReady ? "" : t("downloadNotReady");
  downloadRawBtn.title = disabledTitle;
  downloadOptimizedBtn.title = disabledTitle;
}

function updateAnnotationHeading() {
  if (!annotationListHeadingEl) return;
  annotationListHeadingEl.textContent = tf("annotationListWithCount", { count: annotationCount });
}

function applyTranslations() {
  document.title = t("pageTitle");
  viewerTitleEl.textContent = t("viewerTitle");
  viewerSubtitleEl.textContent = t("viewerSubtitle");
  viewerTipEl.textContent = t("viewerTip");
  titleEl.textContent = currentSession && currentSession.name ? currentSession.name : t("sessionHeading");
  downloadHeadingEl.textContent = t("downloadHeading");
  annotationHeadingEl.textContent = t("annotationHeading");
  annotationGuideEl.textContent = t("annotationGuide");
  annTextEl.placeholder = t("annotationPlaceholder");
  saveAnnBtn.textContent = t("saveButton");
  reloadAnnBtn.textContent = t("reloadButton");
  refreshBtn.textContent = t("refreshButton");
  downloadRawBtn.textContent = t("downloadRawButton");
  downloadOptimizedBtn.textContent = t("downloadOptimizedButton");
  newSessionBtn.textContent = t("newSessionButton");
  zoomInBtn.textContent = t("zoomInButton");
  zoomOutBtn.textContent = t("zoomOutButton");
  homeViewBtn.textContent = t("fitButton");
  fullPageBtn.textContent = t("fullScreenButton");
  goClassicLinkEl.textContent = t("classicMode");
  goWorkflowLinkEl.textContent = t("expertMode");
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
    updateMetaText();
  }
  updateDownloadState();
  updatePendingPointText();
  if (imageCountBadgeEl) {
    const count = currentSession ? currentSession.image_count : 0;
    imageCountBadgeEl.textContent = tf("imageCountLabel", { count });
  }
  updateAnnotationHeading();
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
  if (!viewer) return;
  const marker = document.createElement("div");
  marker.className = "annotation-marker";
  marker.title = annotation.text;
  const viewportPoint = viewer.viewport.imageToViewportCoordinates(annotation.x, annotation.y);
  viewer.addOverlay({
    element: marker,
    location: viewportPoint,
    placement: OpenSeadragon.Placement.CENTER,
  });
}

async function loadAnnotations() {
  const res = await fetch(`/api/sessions/${sessionId}/annotations`);
  if (!res.ok) throw new Error(t("annotationLoadFailed"));
  const rows = await res.json();
  annotationCount = rows.length;
  updateAnnotationHeading();

  annListEl.innerHTML = "";
  if (!rows.length) {
    const li = document.createElement("li");
    li.className = "vwr-empty-item";
    li.textContent = t("annotationEmpty");
    annListEl.appendChild(li);
    return;
  }

  rows.forEach((row) => {
    const li = document.createElement("li");

    const top = document.createElement("div");
    top.className = "vwr-ann-row";
    const point = document.createElement("strong");
    point.textContent = `(${row.x.toFixed(1)}, ${row.y.toFixed(1)})`;
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "secondary vwr-mini-btn";
    removeBtn.textContent = t("deleteLabel");
    removeBtn.addEventListener("click", async () => {
      await fetch(`/api/annotations/${row.id}`, { method: "DELETE" });
      await refreshViewer();
    });
    top.appendChild(point);
    top.appendChild(removeBtn);

    const text = document.createElement("p");
    text.className = "vwr-ann-text";
    text.textContent = row.text;

    li.appendChild(top);
    li.appendChild(text);
    annListEl.appendChild(li);
    createMarker(row);
  });
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
    body: JSON.stringify({
      x: pendingPoint.x,
      y: pendingPoint.y,
      text,
    }),
  });

  if (!res.ok) {
    alert(t("annotationSaveFailed"));
    return;
  }

  annTextEl.value = "";
  pendingPoint = null;
  updatePendingPointText();
  updateSaveButtonState();
  await refreshViewer();
}

function bindViewerToolbar() {
  const ready = Boolean(viewer);
  zoomInBtn.disabled = !ready;
  zoomOutBtn.disabled = !ready;
  homeViewBtn.disabled = !ready;
  fullPageBtn.disabled = !ready;
}

async function initViewer() {
  const session = await getSession();
  currentSession = session;
  currentSessionStatus = session.status;
  titleEl.textContent = session.name || t("sessionHeading");

  if (imageCountBadgeEl) {
    imageCountBadgeEl.textContent = tf("imageCountLabel", { count: session.image_count || 0 });
  }
  setStatusBadge(session.status || "unknown");
  updateMetaText();
  updateDownloadState();
  applyTranslations();

  if (session.status !== "ready") {
    bindViewerToolbar();
    annotationCount = 0;
    updateAnnotationHeading();
    annListEl.innerHTML = `<li class="vwr-empty-item">${t("annotationEmpty")}</li>`;
    return;
  }

  const dziXml = await fetchDziXml();
  const dzi = parseDzi(dziXml);

  viewer = OpenSeadragon({
    id: "openseadragon",
    prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/5.0.1/images/",
    showNavigator: true,
    preserveViewport: true,
    minZoomLevel: 0.5,
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
    updatePendingPointText();
    updateSaveButtonState();
  });

  bindViewerToolbar();
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
  window.location.href = "/";
}

function zoomIn() {
  if (!viewer) return;
  viewer.viewport.zoomBy(1.2);
  viewer.viewport.applyConstraints();
}

function zoomOut() {
  if (!viewer) return;
  viewer.viewport.zoomBy(0.8);
  viewer.viewport.applyConstraints();
}

function goHomeView() {
  if (!viewer) return;
  viewer.viewport.goHome();
}

function toggleFullPage() {
  if (!viewer) return;
  viewer.setFullPage(!viewer.isFullPage());
}

async function refreshViewer() {
  if (viewer) {
    viewer.destroy();
    viewer = null;
  }
  bindViewerToolbar();
  await initViewer();
}

refreshBtn.addEventListener("click", refreshViewer);
reloadAnnBtn.addEventListener("click", loadAnnotations);
saveAnnBtn.addEventListener("click", addAnnotation);
downloadRawBtn.addEventListener("click", downloadRaw);
downloadOptimizedBtn.addEventListener("click", downloadOptimized);
newSessionBtn.addEventListener("click", goToNewSession);

zoomInBtn.addEventListener("click", zoomIn);
zoomOutBtn.addEventListener("click", zoomOut);
homeViewBtn.addEventListener("click", goHomeView);
fullPageBtn.addEventListener("click", toggleFullPage);

annTextEl.addEventListener("input", updateSaveButtonState);
annTextEl.addEventListener("keydown", (evt) => {
  if (evt.key === "Enter") {
    evt.preventDefault();
    addAnnotation();
  }
});

if (window.UI_PREFS) {
  window.UI_PREFS.bindSelectors({
    languageSelectorId: "langSelect",
    themeSelectorId: "themeSelect",
  });
  window.UI_PREFS.onChange(() => applyTranslations());
} else {
  applyTranslations();
}

updatePendingPointText();
updateSaveButtonState();
bindViewerToolbar();

refreshViewer().catch((err) => {
  const message = err && err.message ? err.message : t("unknownError");
  metaEl.textContent = tf("refreshError", { message });
});
