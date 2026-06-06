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

const plannerTitleEl = document.getElementById("plannerTitle");
const plannerSubtitleEl = document.getElementById("plannerSubtitle");
const plannerBadgeEl = document.getElementById("plannerBadge");
const cameraWidthLabelEl = document.getElementById("cameraWidthLabel");
const cameraHeightLabelEl = document.getElementById("cameraHeightLabel");
const targetWidthLabelEl = document.getElementById("targetWidthLabel");
const targetHeightLabelEl = document.getElementById("targetHeightLabel");
const overlapLabelEl = document.getElementById("overlapLabel");
const focusStackLabelEl = document.getElementById("focusStackLabel");
const batteryLabelEl = document.getElementById("batteryLabel");
const calculatePlanBtnEl = document.getElementById("calculatePlanBtn");
const plannerResultEl = document.getElementById("plannerResult");
const cameraWidthEl = document.getElementById("cameraWidth");
const cameraHeightEl = document.getElementById("cameraHeight");
const targetWidthEl = document.getElementById("targetWidth");
const targetHeightEl = document.getElementById("targetHeight");
const overlapPercentEl = document.getElementById("overlapPercent");
const focusStackShotsEl = document.getElementById("focusStackShots");
const safeShotsPerBatteryEl = document.getElementById("safeShotsPerBattery");

let lastResult = null;
let lastPlan = null;

const i18n = {
  en: {
    pageTitle: "Gigapixel Heritage Viewer",
    expertMode: "Expert Mode",
    pageSubtitle: "Upload multiple images and run stitching, DZI generation, and viewer sharing in one flow.",
    sessionName: "Session Name",
    sessionPlaceholder: "e.g. Gyeongbokgung 1910 Scan",
    filesLabel: "Image Files (at least 2)",
    stitchMode: "Stitch Mode",
    scansLabel: "scans (recommended for flat/document scans)",
    panoramaLabel: "panorama (recommended for scene panoramas)",
    startBtn: "Create Session and Start Processing",
    runningBtn: "Processing...",
    nextBtn: "Prepare Next Output",
    langLabel: "Language",
    themeLabel: "Theme",
    lightMode: "Light",
    darkMode: "Night",
    nextReady: "Ready for the next session.",
    createFailed: "Session create failed: {status}",
    uploadFailed: "Upload failed: {message}",
    processFailed: "Process failed to start: {message}",
    statusQueuedHint: " (Waiting in queue. This is normal while the agent is processing an earlier job.)",
    statusText: "Status: {status}{hint}",
    processingFailed: "Processing failed",
    needTwoImages: "Please select at least 2 images.",
    step1: "1/4 Creating session...",
    step2: "2/4 Uploading images...",
    step3: "3/4 Starting stitch pipeline...",
    step4: "4/4 Waiting for completion...",
    completed: "Completed.",
    shareUrl: "Share URL",
    downloadRaw: "Raw BigTIFF",
    downloadOptimized: "Optimized",
    error: "Error: {message}",
    plannerTitle: "Acquisition Planner",
    plannerSubtitle: "Canon R8 capture count, overlap, focus stacking, and battery estimate.",
    plannerBadge: "R8 6000 x 4000",
    cameraWidth: "Camera Width",
    cameraHeight: "Camera Height",
    targetWidth: "Target Width",
    targetHeight: "Target Height",
    overlap: "Overlap (%)",
    focusStack: "Focus Stack Shots",
    battery: "Safe Shots / Battery",
    calculatePlan: "Calculate Capture Plan",
    planFailed: "Plan calculation failed: {message}",
    selectedPlan: "Selected Plan",
    comparison: "Overlap Comparison",
    positions: "positions",
    captures: "captures",
    batteries: "batteries",
    grid: "Grid",
    coverage: "Coverage",
    step: "Step",
    professorAnswer: "At 80% overlap and 6-shot focus stacking, this plan requires {positions} camera positions, {captures} total exposures, and at least {batteries} batteries.",
    overlapCol: "Overlap",
    gridCol: "Grid",
    positionsCol: "Positions",
    capturesCol: "Captures",
    batteriesCol: "Batteries",
    koreanOption: "Korean",
    englishOption: "English",
  },
  ko: {
    pageTitle: "기가픽셀 헤리티지 뷰어",
    expertMode: "전문가 모드",
    pageSubtitle: "다중 이미지를 업로드하고 스티칭, DZI 생성, 웹 뷰어 공유까지 한 번에 실행합니다.",
    sessionName: "세션 이름",
    sessionPlaceholder: "예: 경복궁 1910 스캔",
    filesLabel: "이미지 파일 (최소 2장)",
    stitchMode: "스티칭 모드",
    scansLabel: "scans (문서/평면 촬영 권장)",
    panoramaLabel: "panorama (장면 파노라마 권장)",
    startBtn: "세션 생성 및 처리 시작",
    runningBtn: "처리 중...",
    nextBtn: "다음 결과 준비",
    langLabel: "언어",
    themeLabel: "테마",
    lightMode: "낮 모드",
    darkMode: "밤 모드",
    nextReady: "다음 세션을 준비했습니다.",
    createFailed: "세션 생성 실패: {status}",
    uploadFailed: "업로드 실패: {message}",
    processFailed: "처리 시작 실패: {message}",
    statusQueuedHint: " (대기열에서 순서를 기다리는 중입니다. agent가 앞선 작업을 처리 중이면 정상입니다.)",
    statusText: "상태: {status}{hint}",
    processingFailed: "처리 실패",
    needTwoImages: "이미지를 최소 2장 이상 선택하세요.",
    step1: "1/4 세션 생성 중...",
    step2: "2/4 이미지 업로드 중...",
    step3: "3/4 스티칭 파이프라인 시작 중...",
    step4: "4/4 완료 대기 중...",
    completed: "완료되었습니다.",
    shareUrl: "공유 URL",
    downloadRaw: "원본 BigTIFF",
    downloadOptimized: "최적화 버전",
    error: "오류: {message}",
    plannerTitle: "촬영 계획 계산기",
    plannerSubtitle: "Canon R8 기준 촬영 장수, overlap, focus stacking, 배터리 소요량을 계산합니다.",
    plannerBadge: "R8 6000 x 4000",
    cameraWidth: "카메라 가로 해상도",
    cameraHeight: "카메라 세로 해상도",
    targetWidth: "목표 가로 해상도",
    targetHeight: "목표 세로 해상도",
    overlap: "오버랩 (%)",
    focusStack: "위치당 포커스 스택 장수",
    battery: "배터리당 안전 촬영 컷수",
    calculatePlan: "촬영 계획 계산",
    planFailed: "촬영 계획 계산 실패: {message}",
    selectedPlan: "선택 조건 결과",
    comparison: "오버랩별 비교",
    positions: "촬영 위치",
    captures: "총 노출 컷",
    batteries: "필요 배터리",
    grid: "격자",
    coverage: "커버리지",
    step: "이동 간격",
    professorAnswer: "80% 오버랩과 {stack}장 focus stacking 기준으로, 이 조건은 촬영 위치 {positions}곳, 총 노출 {captures}장, 최소 배터리 {batteries}개가 필요합니다.",
    overlapCol: "오버랩",
    gridCol: "격자",
    positionsCol: "위치 수",
    capturesCol: "총 컷수",
    batteriesCol: "배터리",
    koreanOption: "한국어",
    englishOption: "English",
  },
};

function currentLang() {
  return window.UI_PREFS ? window.UI_PREFS.getLanguage() : "ko";
}

function t(key) {
  const lang = currentLang();
  const pack = i18n[lang] || i18n.ko;
  return pack[key] || i18n.en[key] || key;
}

function tf(key, vars) {
  let text = t(key);
  Object.entries(vars || {}).forEach(([name, value]) => {
    text = text.replaceAll(`{${name}}`, String(value));
  });
  return text;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString(currentLang() === "ko" ? "ko-KR" : "en-US");
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderShare(result) {
  if (!result) {
    shareEl.textContent = "";
    return;
  }
  shareEl.innerHTML = `${t("shareUrl")}: <a href="${result.share_url}">${result.share_url}</a><br/>Download: <a href="/api/sessions/${result.id}/download/raw">${t("downloadRaw")}</a> | <a href="/api/sessions/${result.id}/download/optimized">${t("downloadOptimized")}</a>`;
}

function renderStartButton() {
  const isBusy = startBtn.dataset.busy === "true";
  startBtn.textContent = isBusy ? t("runningBtn") : t("startBtn");
}

function renderPlannerResult(plan) {
  if (!plannerResultEl) return;
  if (!plan) {
    plannerResultEl.innerHTML = "";
    return;
  }

  const selected = plan.selected;
  const rows = (plan.scenarios || [])
    .map((item) => `
      <tr class="${item.overlap_percent === selected.overlap_percent ? "is-selected" : ""}">
        <td>${formatNumber(item.overlap_percent)}%</td>
        <td>${formatNumber(item.columns)} x ${formatNumber(item.rows)}</td>
        <td>${formatNumber(item.positions)}</td>
        <td>${formatNumber(item.captures)}</td>
        <td>${formatNumber(item.batteries)}</td>
      </tr>
    `)
    .join("");

  const professorAnswer = tf("professorAnswer", {
    stack: plan.focus_stack_shots,
    positions: formatNumber(selected.positions),
    captures: formatNumber(selected.captures),
    batteries: formatNumber(selected.batteries),
  });

  plannerResultEl.innerHTML = `
    <div class="planner-summary-card">
      <h3>${t("selectedPlan")}</h3>
      <p class="planner-answer">${escapeHtml(professorAnswer)}</p>
      <dl class="planner-metrics">
        <div><dt>${t("grid")}</dt><dd>${formatNumber(selected.columns)} x ${formatNumber(selected.rows)}</dd></div>
        <div><dt>${t("positions")}</dt><dd>${formatNumber(selected.positions)}</dd></div>
        <div><dt>${t("captures")}</dt><dd>${formatNumber(selected.captures)}</dd></div>
        <div><dt>${t("batteries")}</dt><dd>${formatNumber(selected.batteries)}</dd></div>
        <div><dt>${t("coverage")}</dt><dd>${formatNumber(selected.coverage_width)} x ${formatNumber(selected.coverage_height)}</dd></div>
        <div><dt>${t("step")}</dt><dd>${formatNumber(Math.round(selected.step_x))} x ${formatNumber(Math.round(selected.step_y))}</dd></div>
      </dl>
    </div>
    <div class="planner-table-wrap">
      <h3>${t("comparison")}</h3>
      <table class="planner-table">
        <thead>
          <tr>
            <th>${t("overlapCol")}</th>
            <th>${t("gridCol")}</th>
            <th>${t("positionsCol")}</th>
            <th>${t("capturesCol")}</th>
            <th>${t("batteriesCol")}</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function applyTranslations() {
  document.title = t("pageTitle");
  pageTitleEl.textContent = t("pageTitle");
  openWorkflowLinkEl.textContent = t("expertMode");
  pageSubtitleEl.textContent = t("pageSubtitle");
  sessionNameLabelEl.textContent = t("sessionName");
  sessionNameEl.placeholder = t("sessionPlaceholder");
  filesLabelEl.textContent = t("filesLabel");
  stitchModeLabelEl.textContent = t("stitchMode");
  stitchModeScansEl.textContent = t("scansLabel");
  stitchModePanoramaEl.textContent = t("panoramaLabel");
  renderStartButton();
  nextBtn.textContent = t("nextBtn");
  langLabelEl.textContent = t("langLabel");
  themeLabelEl.textContent = t("themeLabel");

  if (langSelectEl) {
    langSelectEl.options[0].textContent = t("koreanOption");
    langSelectEl.options[1].textContent = t("englishOption");
  }
  if (themeSelectEl) {
    themeSelectEl.options[0].textContent = t("lightMode");
    themeSelectEl.options[1].textContent = t("darkMode");
  }

  if (plannerTitleEl) plannerTitleEl.textContent = t("plannerTitle");
  if (plannerSubtitleEl) plannerSubtitleEl.textContent = t("plannerSubtitle");
  if (plannerBadgeEl) plannerBadgeEl.textContent = t("plannerBadge");
  if (cameraWidthLabelEl) cameraWidthLabelEl.textContent = t("cameraWidth");
  if (cameraHeightLabelEl) cameraHeightLabelEl.textContent = t("cameraHeight");
  if (targetWidthLabelEl) targetWidthLabelEl.textContent = t("targetWidth");
  if (targetHeightLabelEl) targetHeightLabelEl.textContent = t("targetHeight");
  if (overlapLabelEl) overlapLabelEl.textContent = t("overlap");
  if (focusStackLabelEl) focusStackLabelEl.textContent = t("focusStack");
  if (batteryLabelEl) batteryLabelEl.textContent = t("battery");
  if (calculatePlanBtnEl) calculatePlanBtnEl.textContent = t("calculatePlan");

  renderShare(lastResult);
  renderPlannerResult(lastPlan);
}

function setStatus(text, state = "info") {
  statusEl.textContent = text;
  if (text) {
    statusEl.dataset.state = state;
  } else {
    delete statusEl.dataset.state;
  }
}

function setBusy(isBusy) {
  startBtn.disabled = isBusy;
  startBtn.dataset.busy = isBusy ? "true" : "false";
  startBtn.setAttribute("aria-busy", isBusy ? "true" : "false");
  renderStartButton();
}

function numberValue(input, fallback) {
  const value = Number(input && input.value);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function prepareNextSession() {
  sessionNameEl.value = "";
  filesEl.value = "";
  setStatus(t("nextReady"), "success");
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

async function calculatePlan() {
  if (!calculatePlanBtnEl) return;
  calculatePlanBtnEl.disabled = true;
  try {
    const payload = {
      camera_width: Math.round(numberValue(cameraWidthEl, 6000)),
      camera_height: Math.round(numberValue(cameraHeightEl, 4000)),
      target_width: Math.round(numberValue(targetWidthEl, 30000)),
      target_height: Math.round(numberValue(targetHeightEl, 30000)),
      overlap_percent: Number(overlapPercentEl.value || 80),
      focus_stack_shots: Math.round(numberValue(focusStackShotsEl, 6)),
      safe_shots_per_battery: Math.round(numberValue(safeShotsPerBatteryEl, 250)),
    };
    const response = await fetch("/api/acquisition/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    lastPlan = await response.json();
    renderPlannerResult(lastPlan);
  } catch (err) {
    const message = err && err.message ? err.message : String(err);
    plannerResultEl.innerHTML = `<div class="planner-error">${escapeHtml(tf("planFailed", { message }))}</div>`;
  } finally {
    calculatePlanBtnEl.disabled = false;
  }
}

startBtn.addEventListener("click", async () => {
  const name = sessionNameEl.value.trim();
  const files = filesEl.files;
  const mode = stitchModeEl.value;

  if (!files || files.length < 2) {
    setStatus(t("needTwoImages"), "error");
    return;
  }

  setBusy(true);
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

    setStatus(t("completed"), "success");
    lastResult = result;
    renderShare(lastResult);
    nextBtn.classList.remove("hidden");
  } catch (err) {
    setStatus(tf("error", { message: err.message }), "error");
  } finally {
    setBusy(false);
  }
});

nextBtn.addEventListener("click", prepareNextSession);
if (calculatePlanBtnEl) calculatePlanBtnEl.addEventListener("click", calculatePlan);

if (window.UI_PREFS) {
  window.UI_PREFS.bindSelectors({
    languageSelectorId: "langSelect",
    themeSelectorId: "themeSelect",
  });
  window.UI_PREFS.onChange(() => applyTranslations());
} else {
  applyTranslations();
}

applyTranslations();
calculatePlan();
