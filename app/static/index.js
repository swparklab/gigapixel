const statusEl = document.getElementById("status");
const shareEl = document.getElementById("share");
const startBtn = document.getElementById("startBtn");

function setStatus(text) {
  statusEl.textContent = text;
}

async function createSession(name) {
  const res = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name || "Untitled Session" }),
  });
  if (!res.ok) throw new Error(`Session create failed: ${res.status}`);
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
    throw new Error(`Upload failed: ${msg}`);
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
    throw new Error(`Process failed to start: ${msg}`);
  }
  return res.json();
}

async function waitUntilReady(sessionId) {
  while (true) {
    const res = await fetch(`/api/sessions/${sessionId}`);
    const data = await res.json();
    setStatus(`처리 상태: ${data.status}`);

    if (data.status === "ready") {
      return data;
    }
    if (data.status === "failed") {
      throw new Error(data.error_message || "Processing failed");
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
}

startBtn.addEventListener("click", async () => {
  const name = document.getElementById("sessionName").value.trim();
  const files = document.getElementById("files").files;
  const mode = document.getElementById("stitchMode").value;

  if (!files || files.length < 2) {
    setStatus("이미지는 최소 2장 이상 선택해야 합니다.");
    return;
  }

  startBtn.disabled = true;
  shareEl.textContent = "";

  try {
    setStatus("1/4 세션 생성 중...");
    const session = await createSession(name);

    setStatus("2/4 이미지 업로드 중...");
    await uploadImages(session.id, files);

    setStatus("3/4 스티칭/타일링 시작...");
    await processSession(session.id, mode);

    setStatus("4/4 처리 완료 대기 중...");
    const result = await waitUntilReady(session.id);

    setStatus("완료되었습니다.");
    shareEl.innerHTML = `공유 URL: <a href="${result.share_url}">${result.share_url}</a>`;
  } catch (err) {
    setStatus(`오류: ${err.message}`);
  } finally {
    startBtn.disabled = false;
  }
});
