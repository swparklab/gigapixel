const sessionId = window.__SESSION_ID__;
const metaEl = document.getElementById("meta");
const titleEl = document.getElementById("title");
const annListEl = document.getElementById("annList");
const annTextEl = document.getElementById("annText");
const saveAnnBtn = document.getElementById("saveAnnBtn");
const downloadBtn = document.getElementById("downloadBtn");
const newSessionBtn = document.getElementById("newSessionBtn");

let viewer;
let pendingPoint = null;
let currentSessionStatus = "unknown";

function setMeta(text) {
  metaEl.textContent = text;
}

async function getSession() {
  const res = await fetch(`/api/sessions/${sessionId}`);
  if (!res.ok) throw new Error("세션 정보를 가져올 수 없습니다.");
  return res.json();
}

async function fetchDziXml() {
  const res = await fetch(`/api/sessions/${sessionId}/dzi`);
  if (!res.ok) throw new Error("DZI를 찾을 수 없습니다. 처리 완료 후 다시 시도하세요.");
  return res.text();
}

function parseDzi(xmlText) {
  const doc = new DOMParser().parseFromString(xmlText, "application/xml");
  const image = doc.getElementsByTagNameNS("*", "Image")[0];
  const size = doc.getElementsByTagNameNS("*", "Size")[0];
  if (!image || !size) throw new Error("잘못된 DZI 형식입니다.");

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
  if (!res.ok) throw new Error("주석 로딩 실패");
  const rows = await res.json();

  annListEl.innerHTML = "";
  for (const row of rows) {
    const li = document.createElement("li");
    li.textContent = `(${row.x.toFixed(2)}, ${row.y.toFixed(2)}) ${row.text}`;

    const delBtn = document.createElement("button");
    delBtn.textContent = "삭제";
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
    alert("뷰어에서 먼저 위치를 클릭하세요.");
    return;
  }

  const res = await fetch(`/api/sessions/${sessionId}/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x: pendingPoint.x, y: pendingPoint.y, text }),
  });

  if (!res.ok) {
    alert("주석 저장 실패");
    return;
  }

  annTextEl.value = "";
  pendingPoint = null;
  await refreshViewer();
}

async function initViewer() {
  const session = await getSession();
  currentSessionStatus = session.status;
  titleEl.textContent = session.name;
  setMeta(`상태: ${session.status} | 이미지 ${session.image_count}장`);
  downloadBtn.disabled = session.status !== "ready";

  if (session.status !== "ready") {
    setMeta(`상태: ${session.status} (완료 후 새로고침)`);
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
    setMeta(`클릭 좌표: x=${imagePoint.x.toFixed(1)}, y=${imagePoint.y.toFixed(1)}`);
  });

  await loadAnnotations();
}

function downloadResult() {
  if (currentSessionStatus !== "ready") {
    alert("결과물 준비가 끝난 뒤 다운로드할 수 있습니다.");
    return;
  }
  window.location.href = `/api/sessions/${sessionId}/download`;
}

function goToNewSession() {
  window.location.href = "/";
}

async function refreshViewer() {
  if (viewer) {
    viewer.destroy();
    viewer = null;
  }
  await initViewer();
}

document.getElementById("refreshBtn").addEventListener("click", refreshViewer);
saveAnnBtn.addEventListener("click", addAnnotation);
downloadBtn.addEventListener("click", downloadResult);
newSessionBtn.addEventListener("click", goToNewSession);

refreshViewer().catch((err) => {
  setMeta(`오류: ${err.message}`);
});
