let currentJob = null;
let questions = [];
let originalQuestions = [];
let currentSelectPage = 1;
let currentAdjustPage = 1;
let printRegions = [];
let activeRegionId = null;
let dragState = null;
let currentPdfUrl = "";
let currentDownloadUrl = "";
const selected = new Set();

const loginPanel = document.querySelector("#loginPanel");
const loginForm = document.querySelector("#loginForm");
const phoneInput = document.querySelector("#phoneInput");
const passwordInput = document.querySelector("#passwordInput");
const userBar = document.querySelector("#userBar");
const currentUserEl = document.querySelector("#currentUser");
const homeBtn = document.querySelector("#homeBtn");
const uploadCard = document.querySelector("#uploadCard");
const uploadForm = document.querySelector("#uploadForm");
const fileInput = document.querySelector("#fileInput");
const fileSummary = document.querySelector("#fileSummary");
const historyCard = document.querySelector("#historyCard");
const historyList = document.querySelector("#historyList");
const refreshHistoryBtn = document.querySelector("#refreshHistoryBtn");
const statusEl = document.querySelector("#status");
const workspace = document.querySelector("#workspace");
const cleanPanel = document.querySelector("#cleanPanel");
const selectPanel = document.querySelector("#selectPanel");
const adjustPanel = document.querySelector("#adjustPanel");
const previewPanel = document.querySelector("#previewPanel");
const downloadPanel = document.querySelector("#downloadPanel");
const cleanPages = document.querySelector("#cleanPages");
const selectPages = document.querySelector("#selectPages");
const adjustPages = document.querySelector("#adjustPages");
const questionChips = document.querySelector("#questionChips");
const selectPageTabs = document.querySelector("#selectPageTabs");
const adjustPageTabs = document.querySelector("#adjustPageTabs");
const cleanCount = document.querySelector("#cleanCount");
const selectCount = document.querySelector("#selectCount");
const activeLabelEl = document.querySelector("#activeLabel");
const fullExportBtn = document.querySelector("#fullExportBtn");
const chooseQuestionsBtn = document.querySelector("#chooseQuestionsBtn");
const selectAllBtn = document.querySelector("#selectAll");
const clearAllBtn = document.querySelector("#clearAll");
const nextAdjustBtn = document.querySelector("#nextAdjustBtn");
const mergeBtn = document.querySelector("#mergeBtn");
const resetBtn = document.querySelector("#resetBtn");
const regionExportBtn = document.querySelector("#regionExportBtn");
const pdfPreview = document.querySelector("#pdfPreview");
const goDownloadBtn = document.querySelector("#goDownloadBtn");
const openPdfLink = document.querySelector("#openPdfLink");
const downloadLink = document.querySelector("#downloadLink");
const backAdjustBtn = document.querySelector("#backAdjustBtn");
const backPreviewBtn = document.querySelector("#backPreviewBtn");
const busyOverlay = document.querySelector("#busyOverlay");
const busyText = document.querySelector("#busyText");

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setLoginBusy(true);
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        phone: phoneInput.value,
        password: passwordInput.value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "登录失败");
    passwordInput.value = "";
    showAuthenticated(data.user);
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    setLoginBusy(false);
  }
});

homeBtn.addEventListener("click", () => showHome());
refreshHistoryBtn.addEventListener("click", loadHistory);
fileInput.addEventListener("change", updateFileSummary);

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!fileInput.files.length) return;

  setBusy(true, "清痕中");
  const form = new FormData();
  for (const file of fileInput.files) form.append("files", file);

  try {
    const response = await authFetch("/api/jobs", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "清痕失败");
    loadJob(data, { fromHistory: true });
    loadHistory();
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
});

document.querySelectorAll("[data-step]").forEach((button) => {
  button.addEventListener("click", () => setStep(button.dataset.step));
});

fullExportBtn.addEventListener("click", () => exportPdf([]));
chooseQuestionsBtn.addEventListener("click", detectQuestionsIfNeeded);
selectAllBtn.addEventListener("click", () => {
  pageQuestions(currentSelectPage).forEach((question) => selected.add(question.id));
  renderSelectStep();
});
clearAllBtn.addEventListener("click", () => {
  pageQuestions(currentSelectPage).forEach((question) => selected.delete(question.id));
  renderSelectStep();
});
nextAdjustBtn.addEventListener("click", () => {
  if (!selected.size) {
    statusEl.textContent = "请选择题目";
    return;
  }
  buildPrintRegions();
  currentAdjustPage = printRegions[0]?.page || currentSelectPage;
  setStep("adjust");
});
mergeBtn.addEventListener("click", mergeCurrentPageRegions);
resetBtn.addEventListener("click", () => {
  buildPrintRegions();
  renderAdjustStep();
});
regionExportBtn.addEventListener("click", () => {
  if (!printRegions.length) {
    statusEl.textContent = "请先选择题目";
    return;
  }
  exportPdf(exportRegions());
});
backAdjustBtn.addEventListener("click", () => setStep(printRegions.length ? "adjust" : "clean"));
goDownloadBtn.addEventListener("click", () => {
  if (currentPdfUrl) setStep("download");
});
backPreviewBtn.addEventListener("click", () => setStep("preview"));

checkAuth();

async function checkAuth() {
  try {
    const response = await fetch("/api/auth/me");
    if (!response.ok) throw new Error("not authenticated");
    const data = await response.json();
    showAuthenticated(data.user);
  } catch (error) {
    showLogin("请登录");
  }
}

function showAuthenticated(user) {
  loginPanel.classList.add("hidden");
  userBar.classList.remove("hidden");
  currentUserEl.textContent = `${user.username} · ${maskPhone(user.phone)}`;
  if (!currentJob) {
    showHome();
  }
}

function showHome() {
  homeBtn.classList.add("hidden");
  uploadCard.classList.remove("hidden");
  historyCard.classList.remove("hidden");
  workspace.classList.add("hidden");
  statusEl.textContent = "等待上传";
  loadHistory();
}

function showLogin(message) {
  loginPanel.classList.remove("hidden");
  uploadCard.classList.add("hidden");
  historyCard.classList.add("hidden");
  workspace.classList.add("hidden");
  userBar.classList.add("hidden");
  statusEl.textContent = message || "请登录";
}

function resetWorkspace() {
  currentJob = null;
  questions = [];
  originalQuestions = [];
  printRegions = [];
  activeRegionId = null;
  selected.clear();
  fileInput.value = "";
  updateFileSummary();
  clearPreview();
}

function updateFileSummary() {
  const files = Array.from(fileInput.files || []);
  if (!files.length) {
    fileSummary.textContent = "图片或 PDF";
    return;
  }
  if (files.length === 1) {
    fileSummary.textContent = files[0].name;
    return;
  }
  fileSummary.textContent = `${files.length} 个文件`;
}

async function authFetch(url, options) {
  const response = await fetch(url, options);
  if (response.status === 401) {
    resetWorkspace();
    showLogin("登录已失效，请重新登录");
    throw new Error("请重新登录");
  }
  return response;
}

function setLoginBusy(busy) {
  loginForm.querySelector("button").disabled = busy;
  phoneInput.disabled = busy;
  passwordInput.disabled = busy;
  setProcessing(busy, "登录中");
}

async function loadHistory() {
  if (loginPanel.classList.contains("hidden") === false) return;
  try {
    const response = await authFetch("/api/jobs");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "历史加载失败");
    renderHistory(data.jobs || []);
  } catch (error) {
    if (error.message !== "请重新登录") statusEl.textContent = error.message;
  }
}

function renderHistory(jobs) {
  historyList.innerHTML = "";
  if (!jobs.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "暂无历史记录";
    historyList.appendChild(empty);
    return;
  }

  jobs.forEach((job) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "history-item";
    item.innerHTML = `
      <svg class="history-icon"><use href="#i-file"></use></svg>
      <strong>${escapeHtml(job.filename || "未命名")}</strong>
      <span>${formatTime(job.created_at)} · ${job.pages_count || 0} 页 · ${job.questions_count || 0} 题</span>
    `;
    item.addEventListener("click", () => openHistoryJob(job.job_id));
    historyList.appendChild(item);
  });
}

async function openHistoryJob(jobId) {
  setBusy(true, "加载历史中");
  try {
    const response = await authFetch(`/api/jobs/${jobId}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "加载失败");
    loadJob(data);
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

function loadJob(job, options = {}) {
  currentJob = job;
  loadQuestions(job.questions || []);
  selected.clear();
  printRegions = restorePrintRegions(job);
  activeRegionId = null;
  clearPreview();
  currentSelectPage = job.pages[0]?.page || 1;
  currentAdjustPage = printRegions[0]?.page || currentSelectPage;
  uploadCard.classList.add("hidden");
  historyCard.classList.add("hidden");
  workspace.classList.remove("hidden");
  homeBtn.classList.remove("hidden");
  cleanCount.textContent = `${job.pages.length} 页`;
  statusEl.textContent = "清痕完成";
  renderCleanStep();
  if (options.fromHistory && printRegions.length) {
    activeRegionId = printRegions[0].id;
    setStep("adjust");
  } else if (options.fromHistory && questions.length) {
    setStep("select");
  } else {
    setStep("clean");
  }
}

function restorePrintRegions(job) {
  const regions = job.last_export?.regions || [];
  if (!regions.length) return [];

  const restored = regions.map((region, index) => ({
    id: region.id || `restored-${index + 1}`,
    page: Number(region.page),
    label: region.label || `区域 ${index + 1}`,
    bbox: region.bbox.map((value) => Number(value)),
    question_ids: region.question_ids || [],
    sort_index: index,
    source: "history",
    synthetic: true,
  })).sort(compareQuestions);

  restored.forEach((region) => {
    (region.question_ids || []).forEach((id) => selected.add(id));
  });
  return restored;
}

function loadQuestions(items) {
  originalQuestions = items.map((question, index) => normalizeQuestion(question, index));
  questions = originalQuestions.map(cloneQuestion);
}

async function detectQuestionsIfNeeded() {
  if (!currentJob) return;
  if (questions.length) {
    setStep("select");
    return;
  }

  setBusy(true, "识别题目中");
  try {
    const response = await authFetch(`/api/jobs/${currentJob.job_id}/questions`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "识别失败");
    currentJob = data;
    loadQuestions(data.questions || []);
    selected.clear();
    printRegions = [];
    currentSelectPage = data.pages[0]?.page || 1;
    statusEl.textContent = `识别到 ${questions.length} 个题目区域`;
    setStep("select");
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

function setStep(step) {
  cleanPanel.classList.toggle("hidden", step !== "clean");
  selectPanel.classList.toggle("hidden", step !== "select");
  adjustPanel.classList.toggle("hidden", step !== "adjust");
  previewPanel.classList.toggle("hidden", step !== "preview");
  downloadPanel.classList.toggle("hidden", step !== "download");
  document.querySelectorAll("[data-step]").forEach((button) => {
    button.classList.toggle("active", button.dataset.step === step);
  });
  if (step === "clean") renderCleanStep();
  if (step === "select") renderSelectStep();
  if (step === "adjust") renderAdjustStep();
  updateStepState();
}

function updateStepState() {
  const hasQuestions = questions.length > 0;
  const hasSelection = selected.size > 0;
  const hasRegions = printRegions.length > 0;
  document.querySelector('[data-step="select"]').disabled = !hasQuestions;
  document.querySelector('[data-step="adjust"]').disabled = !hasRegions;
  document.querySelector('[data-step="preview"]').disabled = !currentPdfUrl;
  document.querySelector('[data-step="download"]').disabled = !currentPdfUrl;
  nextAdjustBtn.disabled = !hasSelection;
  mergeBtn.disabled = printRegions.filter((region) => region.page === currentAdjustPage).length < 2;
  regionExportBtn.disabled = !hasRegions;
  resetBtn.disabled = !hasSelection;
  goDownloadBtn.disabled = !currentPdfUrl;
  backAdjustBtn.textContent = hasRegions ? "返回调整" : "返回清痕";
  selectCount.textContent = `${selected.size}/${questions.length}`;
  activeLabelEl.textContent = printRegions.find((region) => region.id === activeRegionId)?.label || "未选择";
}

function renderCleanStep() {
  cleanPages.innerHTML = "";
  for (const page of currentJob.pages) {
    cleanPages.appendChild(createPageCard(page, page.cleaned_image_url, [], "clean"));
  }
}

function renderSelectStep() {
  renderPageTabs(selectPageTabs, currentSelectPage, (page) => {
    currentSelectPage = page;
    renderSelectStep();
  }, (page) => {
    const items = pageQuestions(page.page);
    const picked = items.filter((question) => selected.has(question.id)).length;
    return `第 ${page.page} 页 ${picked}/${items.length}`;
  });
  selectPages.innerHTML = "";
  const page = getPage(currentSelectPage);
  if (page) {
    selectPages.appendChild(createPageCard(page, page.image_url, pageQuestions(page.page), "select"));
  }
  renderQuestionChips();
  updateStepState();
}

function renderAdjustStep() {
  if (!printRegions.length && selected.size) buildPrintRegions();
  renderPageTabs(adjustPageTabs, currentAdjustPage, (page) => {
    currentAdjustPage = page;
    renderAdjustStep();
  }, (page) => {
    const count = printRegions.filter((region) => region.page === page.page).length;
    return `第 ${page.page} 页 ${count} 区域`;
  });
  adjustPages.innerHTML = "";
  const page = getPage(currentAdjustPage);
  if (page) {
    adjustPages.appendChild(createPageCard(page, page.cleaned_image_url, printRegions.filter((region) => region.page === page.page), "adjust"));
  }
  updateStepState();
}

function renderPageTabs(container, activePage, onChange, getLabel) {
  container.innerHTML = "";
  for (const page of currentJob.pages) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "page-tab";
    button.classList.toggle("active", page.page === activePage);
    button.textContent = getLabel ? getLabel(page) : `第 ${page.page} 页`;
    button.addEventListener("click", () => onChange(page.page));
    container.appendChild(button);
  }
}

function renderQuestionChips() {
  questionChips.innerHTML = "";
  pageQuestions(currentSelectPage).forEach((question) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.dataset.id = question.id;
    chip.textContent = question.label;
    chip.addEventListener("click", () => {
      toggleQuestion(question.id);
      renderSelectStep();
    });
    questionChips.appendChild(chip);
  });
  syncSelectionClasses();
}

function createPageCard(page, imageUrl, regions, mode) {
  const card = document.createElement("div");
  card.className = "page-card";

  const title = document.createElement("div");
  title.className = "page-title";
  title.textContent = `第 ${page.page} 页`;
  card.appendChild(title);

  const canvas = document.createElement("div");
  canvas.className = "page-canvas";
  canvas.classList.add(`${mode}-canvas`);
  const image = document.createElement("img");
  image.src = imageUrl;
  image.alt = `page ${page.page}`;
  canvas.appendChild(image);

  regions.forEach((region) => {
    const box = document.createElement("button");
    box.type = "button";
    box.className = "region-box";
    box.classList.add(`${mode}-box`);
    box.dataset.id = region.id;
    box.textContent = region.label;
    applyBoxStyle(box, region, page);

    if (mode === "select") {
      box.addEventListener("click", (event) => {
        event.stopPropagation();
        toggleQuestion(region.id);
        renderSelectStep();
      });
    }

    if (mode === "adjust") {
      box.addEventListener("pointerdown", (event) => {
        if (event.target.classList.contains("handle")) return;
        startRegionDrag(event, region, page, box, "move");
      });
      addResizeHandles(box, region, page);
    }

    canvas.appendChild(box);
  });

  card.appendChild(canvas);
  return card;
}

function addResizeHandles(box, region, page) {
  ["nw", "n", "ne", "e", "se", "s", "sw", "w"].forEach((mode) => {
    const handle = document.createElement("span");
    handle.className = `handle ${mode}`;
    handle.addEventListener("pointerdown", (event) => startRegionDrag(event, region, page, box, mode));
    box.appendChild(handle);
  });
}

function toggleQuestion(id) {
  if (selected.has(id)) selected.delete(id);
  else selected.add(id);
  printRegions = [];
  activeRegionId = null;
  clearPreview();
  syncSelectionClasses();
  updateStepState();
}

function syncSelectionClasses() {
  document.querySelectorAll("[data-id]").forEach((element) => {
    const id = element.dataset.id;
    element.classList.toggle("selected", selected.has(id) || id === activeRegionId);
    element.classList.toggle("active", id === activeRegionId);
  });
}

function buildPrintRegions() {
  const regions = [];
  for (const page of currentJob.pages) {
    const all = pageQuestions(page.page);
    const selectedOnPage = all.filter((question) => selected.has(question.id));
    if (!selectedOnPage.length) continue;
    const indexById = new Map(all.map((question, index) => [question.id, index]));
    let group = [];
    let previousIndex = -2;
    for (const question of selectedOnPage) {
      const index = indexById.get(question.id);
      if (group.length && index !== previousIndex + 1) {
        regions.push(regionFromGroup(group, page, all, indexById));
        group = [];
      }
      group.push(question);
      previousIndex = index;
    }
    if (group.length) regions.push(regionFromGroup(group, page, all, indexById));
  }
  printRegions = regions.sort(compareQuestions);
  activeRegionId = printRegions[0]?.id || null;
  clearPreview();
}

function regionFromGroup(group, page, allQuestions, indexById) {
  const xPadding = Math.max(18, Math.round(page.width * 0.01));
  const yPadding = Math.max(18, Math.round(page.height * 0.008));
  const contentLeft = Math.max(0, Math.min(...allQuestions.map((question) => question.bbox[0])) - xPadding);
  const contentRight = Math.min(page.width, Math.max(...allQuestions.map((question) => question.bbox[2])) + xPadding);
  const last = group[group.length - 1];
  const lastIndex = indexById.get(last.id);
  const nextQuestion = allQuestions[lastIndex + 1];
  const union = unionBbox(group.map((question) => question.bbox));
  const bottom = nextQuestion ? Math.max(union[3] + yPadding, nextQuestion.bbox[1] - yPadding) : page.height - yPadding;
  return {
    id: `region-${group[0].id}-${last.id}`,
    page: page.page,
    label: group.length === 1 ? group[0].label : `${group[0].label}-${last.label}`,
    bbox: clampBbox([contentLeft, union[1] - yPadding, contentRight, bottom], page.width, page.height),
    question_ids: group.map((question) => question.id),
    sort_index: group[0].sort_index,
    source: "manual",
    synthetic: true,
  };
}

function mergeCurrentPageRegions() {
  const pageRegions = printRegions.filter((region) => region.page === currentAdjustPage);
  if (pageRegions.length < 2) return;
  const merged = {
    id: `merged-${Date.now()}`,
    page: currentAdjustPage,
    label: `${pageRegions[0].label}-${pageRegions[pageRegions.length - 1].label}`,
    bbox: unionBbox(pageRegions.map((region) => region.bbox)),
    question_ids: pageRegions.flatMap((region) => region.question_ids || []),
    sort_index: pageRegions[0].sort_index,
    source: "manual",
    synthetic: true,
  };
  printRegions = printRegions.filter((region) => region.page !== currentAdjustPage);
  printRegions.push(merged);
  printRegions.sort(compareQuestions);
  activeRegionId = merged.id;
  clearPreview();
  renderAdjustStep();
}

function applyBoxStyle(box, region, page) {
  const [x1, y1, x2, y2] = region.bbox;
  box.style.left = `${(x1 / page.width) * 100}%`;
  box.style.top = `${(y1 / page.height) * 100}%`;
  box.style.width = `${((x2 - x1) / page.width) * 100}%`;
  box.style.height = `${((y2 - y1) / page.height) * 100}%`;
}

function startRegionDrag(event, region, page, box, mode) {
  if (event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  activeRegionId = region.id;
  dragState = {
    box,
    mode,
    page,
    region,
    startClientX: event.clientX,
    startClientY: event.clientY,
    startBbox: [...region.bbox],
  };
  box.setPointerCapture?.(event.pointerId);
  document.addEventListener("pointermove", continueRegionDrag);
  document.addEventListener("pointerup", finishRegionDrag, { once: true });
  document.addEventListener("pointercancel", finishRegionDrag, { once: true });
  syncSelectionClasses();
  updateStepState();
}

function continueRegionDrag(event) {
  if (!dragState) return;
  event.preventDefault();
  const { box, mode, page, region, startBbox, startClientX, startClientY } = dragState;
  const pageRect = box.parentElement.getBoundingClientRect();
  const dx = ((event.clientX - startClientX) / pageRect.width) * page.width;
  const dy = ((event.clientY - startClientY) / pageRect.height) * page.height;
  let [x1, y1, x2, y2] = startBbox;
  if (mode === "move") {
    region.bbox = clampMovedBbox([x1 + dx, y1 + dy, x2 + dx, y2 + dy], page.width, page.height);
  } else {
    if (mode.includes("w")) x1 += dx;
    if (mode.includes("e")) x2 += dx;
    if (mode.includes("n")) y1 += dy;
    if (mode.includes("s")) y2 += dy;
    region.bbox = clampBbox([x1, y1, x2, y2], page.width, page.height);
  }
  applyBoxStyle(box, region, page);
  clearPreview();
}

function finishRegionDrag() {
  if (!dragState) return;
  dragState = null;
  document.removeEventListener("pointermove", continueRegionDrag);
  document.removeEventListener("pointercancel", finishRegionDrag);
  syncSelectionClasses();
}

function exportRegions() {
  return printRegions.sort(compareQuestions).map((region) => ({
    id: region.id,
    page: region.page,
    bbox: region.bbox,
    label: region.label,
    question_ids: region.question_ids || [],
  }));
}

async function exportPdf(regions) {
  if (!currentJob) return;
  setBusy(true, "生成预览中");
  try {
    const response = await authFetch(`/api/jobs/${currentJob.job_id}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ regions }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "生成失败");
    const version = Date.now();
    const previewUrl = appendQueryParam(data.preview_pdf_url, "t", version);
    const downloadUrl = appendQueryParam(data.download_pdf_url, "t", version);
    currentPdfUrl = previewUrl;
    currentDownloadUrl = downloadUrl;
    pdfPreview.src = previewUrl;
    openPdfLink.href = previewUrl;
    downloadLink.href = downloadUrl;
    statusEl.textContent = "预览已生成";
    setStep("preview");
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

function appendQueryParam(url, key, value) {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}${encodeURIComponent(key)}=${encodeURIComponent(value)}`;
}

function clearPreview() {
  currentPdfUrl = "";
  currentDownloadUrl = "";
  pdfPreview.removeAttribute("src");
  openPdfLink.setAttribute("href", "#");
  downloadLink.setAttribute("href", "#");
}

function pageQuestions(page) {
  return questions.filter((question) => question.page === page).sort(compareQuestions);
}

function getPage(page) {
  return currentJob.pages.find((item) => item.page === page);
}

function normalizeQuestion(question, index) {
  return {
    ...question,
    bbox: question.bbox.map((value) => Number(value)),
    sort_index: index,
  };
}

function cloneQuestion(question) {
  return {
    ...question,
    bbox: [...question.bbox],
  };
}

function compareQuestions(a, b) {
  return a.page - b.page || a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0] || a.sort_index - b.sort_index;
}

function unionBbox(bboxes) {
  return [
    Math.min(...bboxes.map((bbox) => bbox[0])),
    Math.min(...bboxes.map((bbox) => bbox[1])),
    Math.max(...bboxes.map((bbox) => bbox[2])),
    Math.max(...bboxes.map((bbox) => bbox[3])),
  ];
}

function clampBbox(bbox, width, height) {
  let [x1, y1, x2, y2] = bbox.map((value) => Math.round(value));
  const minSize = 24;
  x1 = Math.max(0, Math.min(width - minSize, x1));
  y1 = Math.max(0, Math.min(height - minSize, y1));
  x2 = Math.max(x1 + minSize, Math.min(width, x2));
  y2 = Math.max(y1 + minSize, Math.min(height, y2));
  return [x1, y1, x2, y2];
}

function clampMovedBbox(bbox, width, height) {
  let [x1, y1, x2, y2] = bbox.map((value) => Math.round(value));
  const boxWidth = x2 - x1;
  const boxHeight = y2 - y1;
  if (x1 < 0) {
    x2 -= x1;
    x1 = 0;
  }
  if (y1 < 0) {
    y2 -= y1;
    y1 = 0;
  }
  if (x2 > width) {
    x1 -= x2 - width;
    x2 = width;
  }
  if (y2 > height) {
    y1 -= y2 - height;
    y2 = height;
  }
  x1 = Math.max(0, Math.min(width - boxWidth, x1));
  y1 = Math.max(0, Math.min(height - boxHeight, y1));
  return [x1, y1, x1 + boxWidth, y1 + boxHeight];
}

function formatTime(timestamp) {
  if (!timestamp) return "未知时间";
  const date = new Date(Number(timestamp) * 1000);
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function maskPhone(phone) {
  const value = String(phone || "");
  if (value.length < 7) return value;
  return `${value.slice(0, 3)}****${value.slice(-4)}`;
}

function setBusy(busy, text) {
  uploadForm.querySelector("button").disabled = busy;
  fullExportBtn.disabled = busy;
  chooseQuestionsBtn.disabled = busy;
  regionExportBtn.disabled = busy || !printRegions.length;
  goDownloadBtn.disabled = busy || !currentPdfUrl;
  setProcessing(busy, text);
}

function setProcessing(active, text) {
  if (text) {
    statusEl.textContent = text;
    busyText.textContent = text;
  }
  busyOverlay.classList.toggle("hidden", !active);
}
