const statusEl = document.getElementById("status");
const shareEl = document.getElementById("share");
const startBtn = document.getElementById("startBtn");
const nextBtn = document.getElementById("nextBtn");
const sessionNameEl = document.getElementById("sessionName");
const filesEl = document.getElementById("files");
const stitchModeEl = document.getElementById("stitchMode");
const langSelectEl = document.getElementById("langSelect");
const themeSelectEl = document.getElementById("themeSelect");
const pageTitleEl = document.getElementById("pageTitle");
const openWorkflowLinkEl = document.getElementById("openWorkflowLink");
const pageSubtitleEl = document.getElementById("pageSubtitle");
const sessionNameLabelEl = document.getElementById("sessionNameLabel");
const filesLabelEl = document.getElementById("filesLabel");
const stitchModeLabelEl = document.getElementById("stitchModeLabel");
const stitchModeScansEl = document.getElementById("stitchModeScans");
const stitchModePanoramaEl = document.getElementById("stitchModePanorama");
const langLabelEl = document.getElementById("langLabel");
const themeLabelEl = document.getElementById("themeLabel");

let lastResult = null;

const i18n = {
  en: {
    pageTitle: "Gigapixel Heritage Viewer",
    workflowLink: "Open Node Workflow",
    pageSubtitle: "Upload multiple images and run stitching, DZI generation, and viewer sharing in one flow.",
    sessionName: "Session Name",
    sessionPlaceholder: "e.g. Gyeongbokgung 1910 Scan",
    filesLabel: "Image Files (at least 2)",
    stitchMode: "Stitch Mode",
    scansLabel: "scans (recommended for flat/document scans)",
    panoramaLabel: "panorama (recommended for scene panoramas)",
    startBtn: "Create Session and Start Processing",
    nextBtn: "Prepare Next Output",
    langLabel: "Language",
    themeLabel: "Theme",
    lightMode: "Light",
    darkMode: "Night",
    nextReady: "Ready for the next session.",
    createFailed: "Session create failed: {status}",
    uploadFailed: "Upload failed: {message}",
    processFailed: "Process failed to start: {message}",
    statusQueuedHint: " (Check the agent window: `py -3 -m app.agent`)",
    statusText: "Status: {status}{hint}",
    processingFailed: "Processing failed",
    needTwoImages: "Please select at least 2 images.",
    step1: "1/4 Creating session...",
    step2: "2/4 Uploading images...",
    step3: "3/4 Starting stitch pipeline...",
    step4: "4/4 Waiting for completion...",
    completed: "Completed.",
    shareUrl: "Share URL",
    downloadRaw: "Raw High-Res",
    downloadOptimized: "Optimized",
    error: "Error: {message}",
  },
  ko: {
    pageTitle: "기가픽셀 헤리티지 뷰어",
    workflowLink: "노드 워크플로우 열기",
    pageSubtitle: "다중 이미지를 업로드하고 스티칭, DZI 생성, 뷰어 공유까지 한 번에 실행합니다.",
    sessionName: "세션 이름",
    sessionPlaceholder: "예: 경복궁 1910 스캔",
    filesLabel: "이미지 파일 (최소 2장)",
    stitchMode: "스티칭 모드",
    scansLabel: "scans (문서/평면 스캔 권장)",
    panoramaLabel: "panorama (장면 파노라마 권장)",
    startBtn: "세션 생성 및 처리 시작",
    nextBtn: "다음 결과 준비",
    langLabel: "언어",
    themeLabel: "테마",
    lightMode: "밝은 모드",
    darkMode: "밤 모드",
    nextReady: "다음 세션 준비가 완료되었습니다.",
    createFailed: "세션 생성 실패: {status}",
    uploadFailed: "업로드 실패: {message}",
    processFailed: "처리 시작 실패: {message}",
    statusQueuedHint: " (에이전트 창에서 `py -3 -m app.agent` 실행 상태를 확인하세요.)",
    statusText: "상태: {status}{hint}",
    processingFailed: "처리 실패",
    needTwoImages: "이미지를 최소 2장 이상 선택하세요.",
    step1: "1/4 세션 생성 중...",
    step2: "2/4 이미지 업로드 중...",
    step3: "3/4 스티칭 파이프라인 시작...",
    step4: "4/4 완료 대기 중...",
    completed: "완료되었습니다.",
    shareUrl: "공유 URL",
    downloadRaw: "원본 고해상도",
    downloadOptimized: "최적화 버전",
    error: "오류: {message}",
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

function renderShare(result) {
  if (!result) {
    shareEl.textContent = "";
    return;
  }
  shareEl.innerHTML = `${t("shareUrl")}: <a href="${result.share_url}">${result.share_url}</a><br/>Download: <a href="/api/sessions/${result.id}/download/raw">${t("downloadRaw")}</a> | <a href="/api/sessions/${result.id}/download/optimized">${t("downloadOptimized")}</a>`;
}

function applyTranslations() {
  document.title = t("pageTitle");
  pageTitleEl.textContent = t("pageTitle");
  openWorkflowLinkEl.textContent = t("workflowLink");
  pageSubtitleEl.textContent = t("pageSubtitle");
  sessionNameLabelEl.textContent = t("sessionName");
  sessionNameEl.placeholder = t("sessionPlaceholder");
  filesLabelEl.textContent = t("filesLabel");
  stitchModeLabelEl.textContent = t("stitchMode");
  stitchModeScansEl.textContent = t("scansLabel");
  stitchModePanoramaEl.textContent = t("panoramaLabel");
  startBtn.textContent = t("startBtn");
  nextBtn.textContent = t("nextBtn");
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
  renderShare(lastResult);
}

function setStatus(text) {
  statusEl.textContent = text;
}

function prepareNextSession() {
  sessionNameEl.value = "";
  filesEl.value = "";
  setStatus(t("nextReady"));
  lastResult = null;
  renderShare(lastResult);
  nextBtn.classList.add("hidden");
  sessionNameEl.focus();
}

async function createSession(name) {
  const res = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name || "Untitled Session" }),
  });
  if (!res.ok) throw new Error(tf("createFailed", { status: res.status }));
  return res.json();
}

async function uploadImages(sessionId, files) {
  const form = new FormData();
  for (const file of files) form.append("files", file);

  const res = await fetch(`/api/sessions/${sessionId}/images`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const msg = await res.text();
    throw new Error(tf("uploadFailed", { message: msg }));
  }
  return res.json();
}

async function processSession(sessionId, mode) {
  const res = await fetch(`/api/sessions/${sessionId}/process`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (!res.ok) {
    const msg = await res.text();
    throw new Error(tf("processFailed", { message: msg }));
  }
  return res.json();
}

async function waitUntilReady(sessionId) {
  let queuedTicks = 0;
  while (true) {
    const res = await fetch(`/api/sessions/${sessionId}`);
    const data = await res.json();
    if (data.status === "queued") {
      queuedTicks += 1;
    } else {
      queuedTicks = 0;
    }

    const hint = queuedTicks >= 8 ? t("statusQueuedHint") : "";
    setStatus(tf("statusText", { status: data.status, hint }));

    if (data.status === "ready") {
      return data;
    }
    if (data.status === "failed") {
      throw new Error(data.error_message || t("processingFailed"));
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
}

startBtn.addEventListener("click", async () => {
  const name = sessionNameEl.value.trim();
  const files = filesEl.files;
  const mode = stitchModeEl.value;

  if (!files || files.length < 2) {
    setStatus(t("needTwoImages"));
    return;
  }

  startBtn.disabled = true;
  nextBtn.classList.add("hidden");
  lastResult = null;
  renderShare(lastResult);

  try {
    setStatus(t("step1"));
    const session = await createSession(name);

    setStatus(t("step2"));
    await uploadImages(session.id, files);

    setStatus(t("step3"));
    await processSession(session.id, mode);

    setStatus(t("step4"));
    const result = await waitUntilReady(session.id);

    setStatus(t("completed"));
    lastResult = result;
    renderShare(lastResult);
    nextBtn.classList.remove("hidden");
  } catch (err) {
    setStatus(tf("error", { message: err.message }));
  } finally {
    startBtn.disabled = false;
  }
});

nextBtn.addEventListener("click", prepareNextSession);

if (window.UI_PREFS) {
  window.UI_PREFS.bindSelectors({
    languageSelectorId: "langSelect",
    themeSelectorId: "themeSelect",
  });
  window.UI_PREFS.onChange(() => applyTranslations());
} else {
  applyTranslations();
}
