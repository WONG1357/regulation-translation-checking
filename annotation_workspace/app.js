/* global pdfjsLib */

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

const LABELS = [
  "main_chinese_source",
  "english_translation",
  "heading",
  "section_title",
  "table_content",
  "revision_history",
  "definitions_abbreviation",
  "regulatory_reference",
  "clause_matrix",
  "header_footer",
  "page_number",
  "document_metadata",
  "company_name",
  "ignore",
  "wrong_auto_pair",
  "unclear",
];

const PAIR_TYPES = [
  "paragraph_translation",
  "bullet_translation",
  "heading_translation",
  "table_row_translation",
  "table_cell_translation",
  "revision_history_translation",
  "definition_translation",
  "regulatory_reference_translation",
  "clause_matrix_translation",
  "unclear",
];

const RULE_TYPES = [
  "normal_paragraph_pairing",
  "bullet_list_pairing",
  "table_row_pairing",
  "same_line_mixed_pairing",
  "header_footer_ignore",
  "metadata_ignore",
  "revision_history_pairing",
  "definitions_pairing",
  "regulatory_reference_pairing",
  "clause_matrix_pairing",
];

const IGNORE_LABELS = new Set([
  "header_footer",
  "page_number",
  "document_metadata",
  "company_name",
  "ignore",
]);

const state = {
  pdf: null,
  pdfData: null,
  fileName: "",
  pageNumber: 1,
  pageCount: 0,
  scale: 1.25,
  viewport: null,
  mode: "text",
  selection: null,
  editingAnnotationId: null,
  annotations: [],
  manualPairs: [],
  layoutRules: [],
  pendingChinese: [],
  pendingEnglish: [],
  hiddenLabels: new Set(),
  generalNotes: "",
  createdAt: new Date().toISOString(),
  renderToken: 0,
};

const $ = (id) => document.getElementById(id);
const elements = {
  pdfFile: $("pdfFile"),
  localPdfSelect: $("localPdfSelect"),
  openLocalPdf: $("openLocalPdf"),
  fileName: $("fileName"),
  prevPage: $("prevPage"),
  nextPage: $("nextPage"),
  pageNumber: $("pageNumber"),
  pageCount: $("pageCount"),
  zoomOut: $("zoomOut"),
  zoomIn: $("zoomIn"),
  zoomLabel: $("zoomLabel"),
  textMode: $("textMode"),
  rectangleMode: $("rectangleMode"),
  emptyState: $("emptyState"),
  viewerViewport: $("viewerViewport"),
  pageStage: $("pageStage"),
  pdfCanvas: $("pdfCanvas"),
  textLayer: $("textLayer"),
  highlightLayer: $("highlightLayer"),
  selectionLayer: $("selectionLayer"),
  modeStatus: $("modeStatus"),
  selectionHint: $("selectionHint"),
  selectedText: $("selectedText"),
  selectionMeta: $("selectionMeta"),
  annotationLabel: $("annotationLabel"),
  annotationNote: $("annotationNote"),
  saveAnnotation: $("saveAnnotation"),
  deleteAnnotation: $("deleteAnnotation"),
  clearSelection: $("clearSelection"),
  setChinese: $("setChinese"),
  setEnglish: $("setEnglish"),
  filterChips: $("filterChips"),
  annotationList: $("annotationList"),
  pageAnnotationCount: $("pageAnnotationCount"),
  pendingChinese: $("pendingChinese"),
  pendingEnglish: $("pendingEnglish"),
  clearPendingPair: $("clearPendingPair"),
  pairType: $("pairType"),
  pairNote: $("pairNote"),
  createPair: $("createPair"),
  pairList: $("pairList"),
  pairCount: $("pairCount"),
  ruleType: $("ruleType"),
  rulePageRange: $("rulePageRange"),
  ruleSection: $("ruleSection"),
  ruleDescription: $("ruleDescription"),
  addRule: $("addRule"),
  ruleList: $("ruleList"),
  ruleCount: $("ruleCount"),
  summaryCards: $("summaryCards"),
  generalNotes: $("generalNotes"),
  toast: $("toast"),
  importJson: $("importJson"),
};

function init() {
  fillSelect(elements.annotationLabel, LABELS);
  fillSelect(elements.pairType, PAIR_TYPES);
  fillSelect(elements.ruleType, RULE_TYPES);
  bindEvents();
  loadLocalPdfList();
  renderAllPanels();
}

function fillSelect(select, options) {
  select.innerHTML = options
    .map((option) => `<option value="${escapeHtml(option)}">${humanize(option)}</option>`)
    .join("");
}

function bindEvents() {
  elements.pdfFile.addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    await openPdf(await file.arrayBuffer(), file.name);
  });
  elements.openLocalPdf.addEventListener("click", async () => {
    const url = elements.localPdfSelect.value;
    if (!url) return showToast("Choose a PDF from the local folder.");
    const response = await fetch(url);
    await openPdf(await response.arrayBuffer(), decodeURIComponent(url.split("/").pop()));
  });
  elements.prevPage.addEventListener("click", () => changePage(state.pageNumber - 1));
  elements.nextPage.addEventListener("click", () => changePage(state.pageNumber + 1));
  elements.pageNumber.addEventListener("change", () => changePage(Number(elements.pageNumber.value)));
  elements.zoomOut.addEventListener("click", () => changeZoom(-0.15));
  elements.zoomIn.addEventListener("click", () => changeZoom(0.15));
  elements.textMode.addEventListener("click", () => setMode("text"));
  elements.rectangleMode.addEventListener("click", () => setMode("rectangle"));
  elements.textLayer.addEventListener("mouseup", captureTextSelection);
  bindRectangleSelection();

  elements.saveAnnotation.addEventListener("click", saveCurrentAnnotation);
  elements.deleteAnnotation.addEventListener("click", deleteCurrentAnnotation);
  elements.clearSelection.addEventListener("click", clearSelection);
  elements.setChinese.addEventListener("click", () => setSelectionAsRole("chinese_source"));
  elements.setEnglish.addEventListener("click", () => setSelectionAsRole("english_translation"));
  elements.clearPendingPair.addEventListener("click", clearPendingPair);
  elements.createPair.addEventListener("click", createManualPair);
  elements.addRule.addEventListener("click", addLayoutRule);
  elements.generalNotes.addEventListener("input", () => {
    state.generalNotes = elements.generalNotes.value;
  });

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.tab));
  });

  $("exportJson").addEventListener("click", exportCompleteJson);
  $("exportAllJson").addEventListener("click", exportCompleteJson);
  $("exportAnnotationsCsv").addEventListener("click", exportAnnotationsCsv);
  $("exportPairsCsv").addEventListener("click", exportPairsCsv);
  $("exportRulesJson").addEventListener("click", exportRulesJson);
  $("exportCompact").addEventListener("click", exportCompactPackage);
  elements.importJson.addEventListener("change", importAnnotationJson);

  window.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      exportCompleteJson();
    }
    if (event.key === "Escape") clearSelection();
  });
}

async function loadLocalPdfList() {
  try {
    const response = await fetch("/api/pdfs");
    const pdfs = await response.json();
    elements.localPdfSelect.innerHTML =
      `<option value="">Local PDFs…</option>` +
      pdfs.map((item) => `<option value="${escapeHtml(item.url)}">${escapeHtml(item.name)}</option>`).join("");
  } catch {
    elements.localPdfSelect.innerHTML = `<option value="">Local PDFs unavailable</option>`;
  }
}

async function openPdf(arrayBuffer, fileName) {
  state.pdfData = arrayBuffer.slice(0);
  state.fileName = fileName;
  state.pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
  state.pageCount = state.pdf.numPages;
  state.pageNumber = Math.min(Math.max(state.pageNumber, 1), state.pageCount);
  elements.fileName.textContent = fileName;
  elements.pageCount.textContent = state.pageCount;
  elements.emptyState.classList.add("hidden");
  elements.viewerViewport.classList.remove("hidden");
  await renderPage();
  showToast(`Opened ${fileName}`);
}

async function renderPage() {
  if (!state.pdf) return;
  const token = ++state.renderToken;
  const page = await state.pdf.getPage(state.pageNumber);
  if (token !== state.renderToken) return;

  const viewport = page.getViewport({ scale: state.scale });
  state.viewport = viewport;
  const outputScale = window.devicePixelRatio || 1;
  const canvas = elements.pdfCanvas;
  const context = canvas.getContext("2d", { alpha: false });
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  elements.pageStage.style.width = `${viewport.width}px`;
  elements.pageStage.style.height = `${viewport.height}px`;
  elements.textLayer.style.width = `${viewport.width}px`;
  elements.textLayer.style.height = `${viewport.height}px`;

  await page.render({
    canvasContext: context,
    viewport,
    transform: outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0],
  }).promise;
  await renderTextLayer(page, viewport);
  elements.pageNumber.value = state.pageNumber;
  elements.zoomLabel.textContent = `${Math.round(state.scale * 80)}%`;
  renderHighlights();
  renderAnnotationList();
  clearSelection();
}

async function renderTextLayer(page, viewport) {
  const textContent = await page.getTextContent();
  elements.textLayer.innerHTML = "";
  for (const item of textContent.items) {
    const tx = pdfjsLib.Util.transform(viewport.transform, item.transform);
    const angle = Math.atan2(tx[1], tx[0]);
    const fontHeight = Math.hypot(tx[2], tx[3]);
    const style = textContent.styles[item.fontName] || {};
    let top = tx[5];
    if (style.ascent) top -= fontHeight * style.ascent;
    else if (style.descent) top -= fontHeight * (1 + style.descent);
    else top -= fontHeight;

    const span = document.createElement("span");
    span.textContent = item.str;
    span.dataset.text = item.str;
    span.style.left = `${tx[4]}px`;
    span.style.top = `${top}px`;
    span.style.fontSize = `${fontHeight}px`;
    span.style.fontFamily = style.fontFamily || "sans-serif";
    elements.textLayer.appendChild(span);

    const measured = span.getBoundingClientRect().width;
    const targetWidth = item.width * viewport.scale;
    const scaleX = measured > 0 ? targetWidth / measured : 1;
    span.style.transform = `rotate(${angle}rad) scaleX(${scaleX})`;
  }
}

async function changePage(pageNumber) {
  if (!state.pdf) return;
  const next = Math.min(Math.max(Number(pageNumber) || 1, 1), state.pageCount);
  if (next === state.pageNumber) return;
  state.pageNumber = next;
  await renderPage();
}

async function changeZoom(delta) {
  if (!state.pdf) return;
  state.scale = Math.min(Math.max(state.scale + delta, 0.55), 3);
  await renderPage();
}

function setMode(mode) {
  state.mode = mode;
  const rectangle = mode === "rectangle";
  elements.textMode.classList.toggle("active", !rectangle);
  elements.rectangleMode.classList.toggle("active", rectangle);
  elements.pageStage.classList.toggle("rectangle-mode", rectangle);
  elements.modeStatus.textContent = rectangle ? "Rectangle selection mode" : "Text selection mode";
  elements.selectionHint.textContent = rectangle
    ? "Draw a rectangle around text. Text intersecting the area will be captured."
    : "Drag across PDF text to capture it.";
  clearSelection();
}

function captureTextSelection() {
  if (state.mode !== "text" || !state.viewport) return;
  const selection = window.getSelection();
  const text = normalizeText(selection?.toString() || "");
  if (!text || !selection.rangeCount) return;
  const stageRect = elements.pageStage.getBoundingClientRect();
  const rects = Array.from(selection.getRangeAt(0).getClientRects())
    .filter((rect) => rect.width > 1 && rect.height > 1)
    .map((rect) => clientRectToNormalized(rect, stageRect));
  if (!rects.length) return;
  state.selection = createSelectionDraft(text, rects, "text");
  populateSelectionForm();
}

function bindRectangleSelection() {
  let start = null;
  let draft = null;

  elements.selectionLayer.addEventListener("pointerdown", (event) => {
    if (state.mode !== "rectangle") return;
    const rect = elements.pageStage.getBoundingClientRect();
    start = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    draft = document.createElement("div");
    draft.className = "draft-rectangle";
    elements.selectionLayer.innerHTML = "";
    elements.selectionLayer.appendChild(draft);
    elements.selectionLayer.setPointerCapture(event.pointerId);
  });

  elements.selectionLayer.addEventListener("pointermove", (event) => {
    if (!start || !draft) return;
    const rect = elements.pageStage.getBoundingClientRect();
    const current = {
      x: clamp(event.clientX - rect.left, 0, rect.width),
      y: clamp(event.clientY - rect.top, 0, rect.height),
    };
    const box = boxFromPoints(start, current);
    Object.assign(draft.style, {
      left: `${box.x}px`,
      top: `${box.y}px`,
      width: `${box.width}px`,
      height: `${box.height}px`,
    });
  });

  elements.selectionLayer.addEventListener("pointerup", (event) => {
    if (!start || !draft) return;
    const pageRect = elements.pageStage.getBoundingClientRect();
    const current = {
      x: clamp(event.clientX - pageRect.left, 0, pageRect.width),
      y: clamp(event.clientY - pageRect.top, 0, pageRect.height),
    };
    const box = boxFromPoints(start, current);
    start = null;
    draft = null;
    if (box.width < 5 || box.height < 5) {
      elements.selectionLayer.innerHTML = "";
      return;
    }

    const selectedSpans = Array.from(elements.textLayer.querySelectorAll("span"))
      .map((span) => ({ span, rect: span.getBoundingClientRect() }))
      .filter(({ rect }) => intersects(
        { x: rect.left - pageRect.left, y: rect.top - pageRect.top, width: rect.width, height: rect.height },
        box,
      ))
      .sort((a, b) => a.rect.top - b.rect.top || a.rect.left - b.rect.left);
    const text = normalizeText(selectedSpans.map(({ span }) => span.dataset.text).join(" "));
    const normalizedRect = {
      x1: box.x / pageRect.width,
      y1: box.y / pageRect.height,
      x2: (box.x + box.width) / pageRect.width,
      y2: (box.y + box.height) / pageRect.height,
    };
    state.selection = createSelectionDraft(text, [normalizedRect], "rectangle");
    populateSelectionForm();
  });
}

function createSelectionDraft(text, rects, method) {
  const bounds = unionRects(rects);
  return {
    pageNumber: state.pageNumber,
    selectedText: text,
    selectionMethod: method,
    rects,
    coordinates: bounds,
  };
}

function populateSelectionForm() {
  if (!state.selection) return;
  elements.selectedText.value = state.selection.selectedText;
  elements.selectionMeta.textContent =
    `Page ${state.selection.pageNumber} · ${state.selection.selectionMethod} · ` +
    `${state.selection.rects.length} region${state.selection.rects.length === 1 ? "" : "s"}`;
}

function clearSelection() {
  state.selection = null;
  state.editingAnnotationId = null;
  elements.selectedText.value = "";
  elements.annotationNote.value = "";
  elements.selectionMeta.textContent = "No active selection";
  elements.deleteAnnotation.classList.add("hidden");
  elements.saveAnnotation.textContent = "Save annotation";
  elements.selectionLayer.innerHTML = "";
  window.getSelection()?.removeAllRanges();
}

function saveCurrentAnnotation() {
  if (!state.selection && !state.editingAnnotationId) {
    return showToast("Select PDF text or an existing annotation first.");
  }
  const text = normalizeText(elements.selectedText.value);
  if (!text) return showToast("The selection has no text.");

  if (state.editingAnnotationId) {
    const annotation = findAnnotation(state.editingAnnotationId);
    if (!annotation) return;
    annotation.selectedText = text;
    annotation.label = elements.annotationLabel.value;
    annotation.userNote = elements.annotationNote.value.trim();
    showToast("Annotation updated.");
  } else {
    state.annotations.push({
      annotationId: nextId("ANN", state.annotations, "annotationId"),
      fileName: state.fileName,
      pageNumber: state.selection.pageNumber,
      label: elements.annotationLabel.value,
      selectedText: text,
      coordinates: state.selection.coordinates,
      rects: state.selection.rects,
      selectionMethod: state.selection.selectionMethod,
      manualPairId: "",
      pairRole: IGNORE_LABELS.has(elements.annotationLabel.value) ? "ignore" : "standalone_annotation",
      pairType: "",
      userNote: elements.annotationNote.value.trim(),
      createdAt: new Date().toISOString(),
    });
    showToast("Annotation saved.");
  }
  renderAllPanels();
  renderHighlights();
  clearSelection();
}

function setSelectionAsRole(role) {
  let annotation = state.editingAnnotationId ? findAnnotation(state.editingAnnotationId) : null;
  if (!annotation) {
    if (!state.selection) return showToast("Select text first.");
    const label = role === "chinese_source" ? "main_chinese_source" : "english_translation";
    annotation = {
      annotationId: nextId("ANN", state.annotations, "annotationId"),
      fileName: state.fileName,
      pageNumber: state.selection.pageNumber,
      label,
      selectedText: normalizeText(elements.selectedText.value || state.selection.selectedText),
      coordinates: state.selection.coordinates,
      rects: state.selection.rects,
      selectionMethod: state.selection.selectionMethod,
      manualPairId: "",
      pairRole: role,
      pairType: "",
      userNote: elements.annotationNote.value.trim(),
      createdAt: new Date().toISOString(),
    };
    state.annotations.push(annotation);
  } else {
    annotation.label = role === "chinese_source" ? "main_chinese_source" : "english_translation";
    annotation.pairRole = role;
  }
  const pending = role === "chinese_source" ? state.pendingChinese : state.pendingEnglish;
  if (!pending.includes(annotation.annotationId)) pending.push(annotation.annotationId);
  renderAllPanels();
  renderHighlights();
  clearSelection();
  activateTab("pairs");
  showToast(role === "chinese_source" ? "Added to pending Chinese source." : "Added to pending English translation.");
}

function editAnnotation(annotationId) {
  const annotation = findAnnotation(annotationId);
  if (!annotation) return;
  if (annotation.pageNumber !== state.pageNumber) {
    state.pageNumber = annotation.pageNumber;
    renderPage().then(() => editAnnotation(annotationId));
    return;
  }
  state.editingAnnotationId = annotationId;
  state.selection = {
    pageNumber: annotation.pageNumber,
    selectedText: annotation.selectedText,
    rects: annotation.rects,
    coordinates: annotation.coordinates,
    selectionMethod: annotation.selectionMethod,
  };
  elements.selectedText.value = annotation.selectedText;
  elements.annotationLabel.value = annotation.label;
  elements.annotationNote.value = annotation.userNote || "";
  elements.selectionMeta.textContent = `Editing ${annotation.annotationId} · Page ${annotation.pageNumber}`;
  elements.deleteAnnotation.classList.remove("hidden");
  elements.saveAnnotation.textContent = "Update annotation";
  activateTab("annotate");
}

function deleteCurrentAnnotation() {
  if (!state.editingAnnotationId) return;
  deleteAnnotation(state.editingAnnotationId);
  clearSelection();
}

function deleteAnnotation(annotationId) {
  state.annotations = state.annotations.filter((item) => item.annotationId !== annotationId);
  state.pendingChinese = state.pendingChinese.filter((id) => id !== annotationId);
  state.pendingEnglish = state.pendingEnglish.filter((id) => id !== annotationId);
  state.manualPairs = state.manualPairs
    .map((pair) => ({
      ...pair,
      chineseAnnotationIds: pair.chineseAnnotationIds.filter((id) => id !== annotationId),
      englishAnnotationIds: pair.englishAnnotationIds.filter((id) => id !== annotationId),
    }))
    .filter((pair) => pair.chineseAnnotationIds.length && pair.englishAnnotationIds.length);
  state.layoutRules.forEach((rule) => {
    rule.relatedAnnotationIds = rule.relatedAnnotationIds.filter((id) => id !== annotationId);
  });
  renderAllPanels();
  renderHighlights();
  showToast("Annotation deleted.");
}

function clearPendingPair() {
  state.pendingChinese = [];
  state.pendingEnglish = [];
  elements.pairNote.value = "";
  renderPendingPair();
}

function createManualPair() {
  if (!state.pendingChinese.length || !state.pendingEnglish.length) {
    return showToast("Add at least one Chinese and one English annotation.");
  }
  const manualPairId = nextId("PAIR", state.manualPairs, "manualPairId");
  const pairType = elements.pairType.value;
  const allIds = [...state.pendingChinese, ...state.pendingEnglish];
  const annotations = allIds.map(findAnnotation).filter(Boolean);
  annotations.forEach((annotation) => {
    annotation.manualPairId = manualPairId;
    annotation.pairType = pairType;
  });
  state.manualPairs.push({
    manualPairId,
    fileName: state.fileName,
    pageNumber: [...new Set(annotations.map((item) => item.pageNumber))].join(","),
    pairType,
    chineseAnnotationIds: [...state.pendingChinese],
    englishAnnotationIds: [...state.pendingEnglish],
    userNote: elements.pairNote.value.trim(),
    createdAt: new Date().toISOString(),
  });
  clearPendingPair();
  renderAllPanels();
  renderHighlights();
  showToast(`Created ${manualPairId}.`);
}

function deleteManualPair(manualPairId) {
  state.manualPairs = state.manualPairs.filter((pair) => pair.manualPairId !== manualPairId);
  state.annotations.forEach((annotation) => {
    if (annotation.manualPairId === manualPairId) {
      annotation.manualPairId = "";
      annotation.pairType = "";
    }
  });
  state.layoutRules.forEach((rule) => {
    rule.relatedManualPairIds = rule.relatedManualPairIds.filter((id) => id !== manualPairId);
  });
  renderAllPanels();
  renderHighlights();
  showToast("Manual pair deleted.");
}

function addLayoutRule() {
  const description = elements.ruleDescription.value.trim();
  if (!description) return showToast("Describe the layout rule first.");
  const linkedAnnotationIds = [...new Set([...state.pendingChinese, ...state.pendingEnglish])];
  const linkedPairIds = state.manualPairs
    .filter((pair) => [...pair.chineseAnnotationIds, ...pair.englishAnnotationIds].some((id) => linkedAnnotationIds.includes(id)))
    .map((pair) => pair.manualPairId);
  state.layoutRules.push({
    ruleId: nextId("RULE", state.layoutRules, "ruleId"),
    pageRange: elements.rulePageRange.value.trim() || String(state.pageNumber),
    section: elements.ruleSection.value.trim(),
    ruleType: elements.ruleType.value,
    description,
    relatedAnnotationIds: linkedAnnotationIds,
    relatedManualPairIds: linkedPairIds,
    createdAt: new Date().toISOString(),
  });
  elements.ruleDescription.value = "";
  elements.ruleSection.value = "";
  renderAllPanels();
  showToast("Layout rule added.");
}

function deleteLayoutRule(ruleId) {
  state.layoutRules = state.layoutRules.filter((rule) => rule.ruleId !== ruleId);
  renderAllPanels();
  showToast("Layout rule deleted.");
}

function renderHighlights() {
  elements.highlightLayer.innerHTML = "";
  if (!state.viewport) return;
  const width = state.viewport.width;
  const height = state.viewport.height;
  state.annotations
    .filter((annotation) => annotation.pageNumber === state.pageNumber && !state.hiddenLabels.has(annotation.label))
    .forEach((annotation) => {
      (annotation.rects?.length ? annotation.rects : [annotation.coordinates]).forEach((rect) => {
        const highlight = document.createElement("button");
        highlight.type = "button";
        highlight.className = `annotation-highlight ${highlightClass(annotation.label)}`;
        highlight.title = `${annotation.annotationId}: ${annotation.selectedText}`;
        Object.assign(highlight.style, {
          left: `${rect.x1 * width}px`,
          top: `${rect.y1 * height}px`,
          width: `${Math.max((rect.x2 - rect.x1) * width, 3)}px`,
          height: `${Math.max((rect.y2 - rect.y1) * height, 3)}px`,
        });
        highlight.addEventListener("click", () => editAnnotation(annotation.annotationId));
        elements.highlightLayer.appendChild(highlight);
      });
    });
}

function renderAllPanels() {
  renderAnnotationList();
  renderPendingPair();
  renderPairList();
  renderRuleList();
  renderSummary();
}

function renderAnnotationList() {
  const pageAnnotations = state.annotations.filter((item) => item.pageNumber === state.pageNumber);
  elements.pageAnnotationCount.textContent = pageAnnotations.length;
  const labelsOnPage = [...new Set(pageAnnotations.map((item) => item.label))];
  elements.filterChips.innerHTML = labelsOnPage.map((label) => `
    <button class="filter-chip ${state.hiddenLabels.has(label) ? "off" : ""}" data-label="${escapeHtml(label)}">
      ${humanize(label)}
    </button>`).join("");
  elements.filterChips.querySelectorAll(".filter-chip").forEach((button) => {
    button.addEventListener("click", () => {
      const label = button.dataset.label;
      if (state.hiddenLabels.has(label)) state.hiddenLabels.delete(label);
      else state.hiddenLabels.add(label);
      renderAnnotationList();
      renderHighlights();
    });
  });

  if (!pageAnnotations.length) {
    elements.annotationList.innerHTML = `<div class="empty-list">No annotations on page ${state.pageNumber}.</div>`;
    return;
  }
  elements.annotationList.innerHTML = pageAnnotations.map((annotation) => `
    <article class="item-card" data-annotation-id="${escapeHtml(annotation.annotationId)}">
      <div class="item-card-top">
        <span class="item-label">${humanize(annotation.label)}</span>
        <span class="item-meta">${annotation.annotationId}${annotation.manualPairId ? ` · ${annotation.manualPairId}` : ""}</span>
      </div>
      <div class="item-text">${escapeHtml(truncate(annotation.selectedText, 180))}</div>
      ${annotation.userNote ? `<div class="item-note">${escapeHtml(annotation.userNote)}</div>` : ""}
      <div class="item-actions">
        <button class="mini-button add-chinese" data-id="${annotation.annotationId}">+ Chinese</button>
        <button class="mini-button add-english" data-id="${annotation.annotationId}">+ English</button>
        <button class="mini-button delete-ann" data-id="${annotation.annotationId}">Delete</button>
      </div>
    </article>`).join("");
  elements.annotationList.querySelectorAll(".item-card").forEach((card) => {
    card.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      editAnnotation(card.dataset.annotationId);
    });
  });
  elements.annotationList.querySelectorAll(".add-chinese").forEach((button) => {
    button.addEventListener("click", () => addExistingToPending(button.dataset.id, "chinese"));
  });
  elements.annotationList.querySelectorAll(".add-english").forEach((button) => {
    button.addEventListener("click", () => addExistingToPending(button.dataset.id, "english"));
  });
  elements.annotationList.querySelectorAll(".delete-ann").forEach((button) => {
    button.addEventListener("click", () => deleteAnnotation(button.dataset.id));
  });
}

function addExistingToPending(annotationId, role) {
  const annotation = findAnnotation(annotationId);
  if (!annotation) return;
  const pending = role === "chinese" ? state.pendingChinese : state.pendingEnglish;
  if (!pending.includes(annotationId)) pending.push(annotationId);
  annotation.pairRole = role === "chinese" ? "chinese_source" : "english_translation";
  if (role === "chinese") annotation.label = "main_chinese_source";
  else annotation.label = "english_translation";
  renderAllPanels();
  renderHighlights();
  activateTab("pairs");
}

function renderPendingPair() {
  renderPendingList(elements.pendingChinese, state.pendingChinese, "No Chinese annotations selected");
  renderPendingList(elements.pendingEnglish, state.pendingEnglish, "No English annotations selected");
}

function renderPendingList(container, ids, emptyText) {
  if (!ids.length) {
    container.className = "pending-list empty";
    container.textContent = emptyText;
    return;
  }
  container.className = "pending-list";
  container.innerHTML = ids.map((id) => {
    const annotation = findAnnotation(id);
    return annotation
      ? `<div class="pending-item">${escapeHtml(annotation.annotationId)} · ${escapeHtml(truncate(annotation.selectedText, 105))}</div>`
      : "";
  }).join("");
}

function renderPairList() {
  elements.pairCount.textContent = state.manualPairs.length;
  if (!state.manualPairs.length) {
    elements.pairList.innerHTML = `<div class="empty-list">No manual bilingual pairs yet.</div>`;
    return;
  }
  elements.pairList.innerHTML = state.manualPairs.map((pair) => {
    const zh = pair.chineseAnnotationIds.map(findAnnotation).filter(Boolean).map((item) => item.selectedText).join(" ");
    const en = pair.englishAnnotationIds.map(findAnnotation).filter(Boolean).map((item) => item.selectedText).join(" ");
    return `
      <article class="item-card">
        <div class="item-card-top">
          <span class="item-label">${escapeHtml(pair.manualPairId)} · ${humanize(pair.pairType)}</span>
          <span class="item-meta">p. ${escapeHtml(String(pair.pageNumber))}</span>
        </div>
        <div class="item-text"><strong>中:</strong> ${escapeHtml(truncate(zh, 125))}</div>
        <div class="item-text"><strong>EN:</strong> ${escapeHtml(truncate(en, 125))}</div>
        ${pair.userNote ? `<div class="item-note">${escapeHtml(pair.userNote)}</div>` : ""}
        <div class="item-actions"><button class="mini-button delete-pair" data-id="${pair.manualPairId}">Delete pair</button></div>
      </article>`;
  }).join("");
  elements.pairList.querySelectorAll(".delete-pair").forEach((button) => {
    button.addEventListener("click", () => deleteManualPair(button.dataset.id));
  });
}

function renderRuleList() {
  elements.ruleCount.textContent = state.layoutRules.length;
  if (!state.layoutRules.length) {
    elements.ruleList.innerHTML = `<div class="empty-list">No layout rules yet.</div>`;
    return;
  }
  elements.ruleList.innerHTML = state.layoutRules.map((rule) => `
    <article class="item-card">
      <div class="item-card-top">
        <span class="item-label">${escapeHtml(rule.ruleId)} · ${humanize(rule.ruleType)}</span>
        <span class="item-meta">p. ${escapeHtml(rule.pageRange || "—")}</span>
      </div>
      <div class="item-text">${escapeHtml(rule.description)}</div>
      ${rule.section ? `<div class="item-note">Section: ${escapeHtml(rule.section)}</div>` : ""}
      <div class="item-note">${rule.relatedAnnotationIds.length} annotations · ${rule.relatedManualPairIds.length} pairs</div>
      <div class="item-actions"><button class="mini-button delete-rule" data-id="${rule.ruleId}">Delete rule</button></div>
    </article>`).join("");
  elements.ruleList.querySelectorAll(".delete-rule").forEach((button) => {
    button.addEventListener("click", () => deleteLayoutRule(button.dataset.id));
  });
}

function renderSummary() {
  const ignored = state.annotations.filter((item) => IGNORE_LABELS.has(item.label)).length;
  const tableExamples = state.annotations.filter((item) =>
    ["table_content", "revision_history", "definitions_abbreviation", "regulatory_reference", "clause_matrix"].includes(item.label)
  ).length;
  elements.summaryCards.innerHTML = [
    [state.annotations.length, "annotations"],
    [state.manualPairs.length, "manual pairs"],
    [state.layoutRules.length, "layout rules"],
    [ignored, "ignored examples"],
    [tableExamples, "table examples"],
    [new Set(state.annotations.map((item) => item.pageNumber)).size, "pages annotated"],
  ].map(([number, label]) => `
    <div class="summary-card"><strong>${number}</strong><span>${label}</span></div>
  `).join("");
  elements.generalNotes.value = state.generalNotes;
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
  $(`${name}Tab`).classList.add("active");
}

function exportCompleteJson() {
  downloadBlob(
    `${safeStem(state.fileName || "pdf")}_annotations.json`,
    JSON.stringify(buildExportPayload(), null, 2),
    "application/json",
  );
}

function buildExportPayload() {
  return {
    schemaVersion: "1.0",
    workspace: "standalone_pdf_annotation_workspace",
    sourcePdfFileName: state.fileName,
    createdAt: state.createdAt,
    exportedAt: new Date().toISOString(),
    pageCount: state.pageCount,
    coordinateSystem: {
      type: "normalized_page_coordinates",
      origin: "top_left",
      range: "0_to_1",
      fields: ["x1", "y1", "x2", "y2"],
    },
    annotations: state.annotations,
    manualPairs: state.manualPairs.map(expandPairForExport),
    layoutRules: state.layoutRules,
    hiddenAnnotationTypes: [...state.hiddenLabels],
    notes: state.generalNotes,
    intendedUses: [
      "identify repeated headers and footers",
      "identify main content regions",
      "learn Chinese-English pairing patterns",
      "avoid reviewing metadata",
      "improve pair confidence scoring",
      "rebuild corrected bilingual pairs",
    ],
  };
}

function expandPairForExport(pair) {
  const chinese = pair.chineseAnnotationIds.map(findAnnotation).filter(Boolean);
  const english = pair.englishAnnotationIds.map(findAnnotation).filter(Boolean);
  return {
    ...pair,
    chineseText: chinese.map((item) => item.selectedText).join(" "),
    englishText: english.map((item) => item.selectedText).join(" "),
    chineseCoordinates: chinese.map((item) => ({
      annotationId: item.annotationId,
      pageNumber: item.pageNumber,
      coordinates: item.coordinates,
      rects: item.rects,
    })),
    englishCoordinates: english.map((item) => ({
      annotationId: item.annotationId,
      pageNumber: item.pageNumber,
      coordinates: item.coordinates,
      rects: item.rects,
    })),
  };
}

function exportAnnotationsCsv() {
  const rows = state.annotations.map((item) => ({
    annotation_id: item.annotationId,
    file_name: item.fileName || state.fileName,
    page_number: item.pageNumber,
    label: item.label,
    selected_text: item.selectedText,
    x1: item.coordinates.x1,
    y1: item.coordinates.y1,
    x2: item.coordinates.x2,
    y2: item.coordinates.y2,
    manual_pair_id: item.manualPairId || "",
    pair_role: item.pairRole || "standalone_annotation",
    pair_type: item.pairType || "",
    user_note: item.userNote || "",
  }));
  downloadCsv(`${safeStem(state.fileName || "pdf")}_annotations.csv`, rows);
}

function exportPairsCsv() {
  const rows = state.manualPairs.map((pair) => {
    const expanded = expandPairForExport(pair);
    return {
      manual_pair_id: pair.manualPairId,
      file_name: pair.fileName || state.fileName,
      page_number: pair.pageNumber,
      pair_type: pair.pairType,
      chinese_text: expanded.chineseText,
      english_text: expanded.englishText,
      chinese_annotation_ids: pair.chineseAnnotationIds.join("|"),
      english_annotation_ids: pair.englishAnnotationIds.join("|"),
      chinese_coordinates: JSON.stringify(expanded.chineseCoordinates),
      english_coordinates: JSON.stringify(expanded.englishCoordinates),
      user_note: pair.userNote || "",
    };
  });
  downloadCsv(`${safeStem(state.fileName || "pdf")}_manual_pairs.csv`, rows);
}

function exportRulesJson() {
  downloadBlob(
    `${safeStem(state.fileName || "pdf")}_layout_rules.json`,
    JSON.stringify({
      sourcePdfFileName: state.fileName,
      exportedAt: new Date().toISOString(),
      layoutRules: state.layoutRules,
    }, null, 2),
    "application/json",
  );
}

function exportCompactPackage() {
  const ignored = state.annotations.filter((item) => IGNORE_LABELS.has(item.label)).slice(0, 12);
  const tables = state.annotations.filter((item) =>
    ["table_content", "revision_history", "definitions_abbreviation", "regulatory_reference", "clause_matrix"].includes(item.label)
  ).slice(0, 15);
  const pairs = state.manualPairs.slice(0, 30).map(expandPairForExport);
  const lines = [
    "# PDF annotation teaching package",
    "",
    `- Source PDF: ${state.fileName || "Not recorded"}`,
    `- Pages: ${state.pageCount || "Unknown"}`,
    `- Annotations: ${state.annotations.length}`,
    `- Manual pairs: ${state.manualPairs.length}`,
    `- Layout rules: ${state.layoutRules.length}`,
    "",
    "## Selected Chinese-English examples",
    "```json",
    JSON.stringify(pairs, null, 2),
    "```",
    "",
    "## Ignored header / footer / metadata examples",
    "```json",
    JSON.stringify(ignored, null, 2),
    "```",
    "",
    "## Table and structured-content examples",
    "```json",
    JSON.stringify(tables, null, 2),
    "```",
    "",
    "## Layout rules",
    "```json",
    JSON.stringify(state.layoutRules, null, 2),
    "```",
    "",
    "## User notes",
    state.generalNotes || "None",
  ];
  downloadBlob(
    `${safeStem(state.fileName || "pdf")}_chatgpt_package.md`,
    lines.join("\n"),
    "text/markdown",
  );
}

async function importAnnotationJson(event) {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const payload = JSON.parse(await file.text());
    state.fileName = payload.sourcePdfFileName || state.fileName;
    state.createdAt = payload.createdAt || new Date().toISOString();
    state.pageCount = payload.pageCount || state.pageCount;
    state.annotations = normalizeImportedAnnotations(payload.annotations || []);
    state.manualPairs = payload.manualPairs || [];
    state.layoutRules = payload.layoutRules || [];
    state.hiddenLabels = new Set(payload.hiddenAnnotationTypes || []);
    state.generalNotes = payload.notes || "";
    state.pendingChinese = [];
    state.pendingEnglish = [];
    elements.fileName.textContent = state.fileName || "Imported annotations";
    renderAllPanels();
    renderHighlights();
    showToast("Annotation JSON imported. Open the matching PDF to restore the page view.");
  } catch (error) {
    showToast(`Could not import JSON: ${error.message}`);
  } finally {
    event.target.value = "";
  }
}

function normalizeImportedAnnotations(annotations) {
  return annotations.map((item) => ({
    ...item,
    annotationId: item.annotationId || item.annotation_id,
    fileName: item.fileName || item.file_name || state.fileName,
    pageNumber: Number(item.pageNumber || item.page_number),
    selectedText: item.selectedText || item.selected_text || "",
    userNote: item.userNote || item.user_note || "",
    manualPairId: item.manualPairId || item.manual_pair_id || "",
    pairRole: item.pairRole || item.pair_role || "standalone_annotation",
    pairType: item.pairType || item.pair_type || "",
    rects: item.rects || [item.coordinates],
  }));
}

function clientRectToNormalized(rect, stageRect) {
  return {
    x1: clamp((rect.left - stageRect.left) / stageRect.width, 0, 1),
    y1: clamp((rect.top - stageRect.top) / stageRect.height, 0, 1),
    x2: clamp((rect.right - stageRect.left) / stageRect.width, 0, 1),
    y2: clamp((rect.bottom - stageRect.top) / stageRect.height, 0, 1),
  };
}

function unionRects(rects) {
  return {
    x1: Math.min(...rects.map((rect) => rect.x1)),
    y1: Math.min(...rects.map((rect) => rect.y1)),
    x2: Math.max(...rects.map((rect) => rect.x2)),
    y2: Math.max(...rects.map((rect) => rect.y2)),
  };
}

function findAnnotation(id) {
  return state.annotations.find((item) => item.annotationId === id);
}

function nextId(prefix, items, field) {
  const max = items.reduce((current, item) => {
    const match = String(item[field] || "").match(/(\d+)$/);
    return Math.max(current, match ? Number(match[1]) : 0);
  }, 0);
  return `${prefix}-${String(max + 1).padStart(4, "0")}`;
}

function downloadCsv(fileName, rows) {
  if (!rows.length) return showToast("There is no data to export yet.");
  const headers = Object.keys(rows[0]);
  const csv = [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(",")),
  ].join("\n");
  downloadBlob(fileName, `\uFEFF${csv}`, "text/csv;charset=utf-8");
}

function csvCell(value) {
  const text = value == null ? "" : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadBlob(fileName, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  showToast(`Downloaded ${fileName}`);
}

function highlightClass(label) {
  if (LABELS.includes(label)) return label;
  return label === "wrong_auto_pair" ? label : "default";
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("show");
  clearTimeout(showToast.timeout);
  showToast.timeout = setTimeout(() => elements.toast.classList.remove("show"), 2400);
}

function humanize(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function safeStem(value) {
  return String(value || "document")
    .replace(/\.[^.]+$/, "")
    .replace(/[^\p{L}\p{N}_-]+/gu, "_")
    .replace(/^_+|_+$/g, "") || "document";
}

function normalizeText(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function truncate(text, length) {
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function boxFromPoints(start, end) {
  return {
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
  };
}

function intersects(a, b) {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

init();
