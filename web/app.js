const form = document.getElementById("design-form");
const workspace = document.getElementById("workspace");
const viewerContainer = document.getElementById("viewer-3d");
const resetLayoutButton = document.getElementById("reset-layout");
const aiAssistantForm = document.getElementById("ai-assistant-form");
const aiPromptInput = document.getElementById("ai-prompt");
const aiApplyButton = document.getElementById("ai-apply-button");
const aiLoading = document.getElementById("ai-loading");
const aiCommandStatus = document.getElementById("ai-command-status");
const aiToggleHandle = document.querySelector("[data-ai-toggle]");
const ASSET_VERSION = "20260414-9";
const DEFAULT_LAYOUT_SPLIT_X = 50;
const DEFAULT_LAYOUT_SPLIT_Y = 50;
const MIN_PANEL_WIDTH_PX = 260;
const MIN_PANEL_HEIGHT_PX = 220;
const PANEL_SLOT_CLASSES = [
  "quadrant-inputs",
  "quadrant-model",
  "quadrant-results",
  "quadrant-notes",
];
const HANDLE_DIRECTION_CLASSES = [
  "panel-resize-handle-left",
  "panel-resize-handle-right",
  "panel-resize-handle-top",
  "panel-resize-handle-bottom",
  "panel-resize-handle-corner-nw",
  "panel-resize-handle-corner-ne",
  "panel-resize-handle-corner-sw",
  "panel-resize-handle-corner-se",
];
let viewer = {
  update() {},
};
let latestResult = null;

const elements = {
  statusPill: document.getElementById("status-pill"),
  governingCheck: document.getElementById("governing-check"),
  requiredArea: document.getElementById("required-area"),
  recommendedSize: document.getElementById("recommended-size"),
  bearingSummary: document.getElementById("bearing-summary"),
  eccentricitySummary: document.getElementById("eccentricity-summary"),
  qmax: document.getElementById("qmax"),
  qmin: document.getElementById("qmin"),
  bearingUtilization: document.getElementById("bearing-utilization"),
  bearingPass: document.getElementById("bearing-pass"),
  middleThird: document.getElementById("middle-third"),
  fullContact: document.getElementById("full-contact"),
  outsideScope: document.getElementById("outside-scope"),
  warningsList: document.getElementById("warnings-list"),
  assumptionsList: document.getElementById("assumptions-list"),
  prelimNote: document.getElementById("prelim-note"),
  aiChangesList: document.getElementById("ai-changes-list"),
  aiExplanation: document.getElementById("ai-explanation"),
  aiWarningsList: document.getElementById("ai-warnings-list"),
};

const windows = [...document.querySelectorAll(".panel-window")];

let debounceTimer = null;
let maximizedWindow = null;
const windowPositions = new Map();
let activeResizeState = null;
let draggedPanel = null;
let activePanelSwapState = null;

initializeLayout();

function initializeLayout() {
  initializeViewer();
  resetLayout();
  bindWorkspaceResizers();
  bindWindowActions();
  bindWindowMaximize();
  bindPanelSwapping();
  bindAiAssistant();
  form.addEventListener("input", scheduleCalculation, { passive: true });
  resetLayoutButton.addEventListener("click", resetLayout);
  window.addEventListener("keydown", handleKeydown);
  window.addEventListener("load", calculate);
}

async function initializeViewer() {
  try {
    const module = await import(`/viewer3d.js?v=${ASSET_VERSION}`);
    viewer = new module.FootingViewer(viewerContainer);
  } catch (error) {
    viewerContainer.innerHTML = '<div class="viewer-overlay"><span>3D preview unavailable</span><span>Layout and calculations are still active</span></div>';
    console.error("Viewer failed to initialize", error);
  }
}

function resetLayout() {
  if (maximizedWindow) {
    restoreWindow(maximizedWindow);
  }
  setWorkspaceSplit(DEFAULT_LAYOUT_SPLIT_X, DEFAULT_LAYOUT_SPLIT_Y);
  resetPanelSlots();
  syncPanelResizeHandles();
}

function bindWindowActions() {
  windows.forEach((windowElement) => {
    windowElement.querySelectorAll(".window-action").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.dataset.action;
        if (action === "toggle-maximize") {
          toggleMaximize(windowElement);
        }
      });
    });
  });
}

function bindWindowMaximize() {
  windows.forEach((windowElement) => {
    const handle = windowElement.querySelector("[data-window-handle]");
    handle.addEventListener("dblclick", (event) => {
      if (event.target.closest(".window-action")) {
        return;
      }
      toggleMaximize(windowElement);
    });
  });
}

function bindPanelSwapping() {
  windows.forEach((windowElement) => {
    const handle = windowElement.querySelector("[data-window-handle]");
    if (!handle) {
      return;
    }

    handle.addEventListener("pointerdown", (event) => {
      startPanelSwap(event, windowElement, handle);
    });
  });
}

function bindAiAssistant() {
  if (!aiAssistantForm) {
    return;
  }

  if (aiToggleHandle) {
    aiToggleHandle.addEventListener("dblclick", (event) => {
      if (event.target.closest("input, button")) {
        return;
      }
      toggleAiAssistantExpanded();
    });
  }

  aiAssistantForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await applyAiSuggestion();
  });
}

function toggleAiAssistantExpanded() {
  return setAiAssistantExpanded(!aiAssistantForm.classList.contains("is-expanded"));
}

function setAiAssistantExpanded(expanded) {
  const nextExpanded = !aiAssistantForm.classList.contains("is-expanded");
  const resolvedExpanded = expanded ?? nextExpanded;
  aiAssistantForm.classList.toggle("is-expanded", resolvedExpanded);
  aiAssistantForm.setAttribute("aria-expanded", String(resolvedExpanded));
  return resolvedExpanded;
}

function toggleMaximize(windowElement) {
  if (windowElement.classList.contains("is-maximized")) {
    restoreWindow(windowElement);
    return;
  }

  if (maximizedWindow && maximizedWindow !== windowElement) {
    restoreWindow(maximizedWindow);
  }

  const parent = windowElement.parentElement;
  windowPositions.set(windowElement, {
    parent,
    nextSibling: windowElement.nextElementSibling,
  });

  workspace.classList.add("has-maximized");
  document.body.classList.add("has-maximized-window");
  windowElement.classList.add("is-maximized");
  document.body.appendChild(windowElement);
  updateMaximizeButton(windowElement, true);
  maximizedWindow = windowElement;
}

function restoreWindow(windowElement) {
  const stored = windowPositions.get(windowElement);
  if (!stored) {
    return;
  }

  if (stored.nextSibling && stored.nextSibling.parentElement === stored.parent) {
    stored.parent.insertBefore(windowElement, stored.nextSibling);
  } else {
    stored.parent.appendChild(windowElement);
  }

  windowElement.classList.remove("is-maximized");
  updateMaximizeButton(windowElement, false);
  workspace.classList.remove("has-maximized");
  document.body.classList.remove("has-maximized-window");
  windowPositions.delete(windowElement);

  if (maximizedWindow === windowElement) {
    maximizedWindow = null;
  }
}

function updateMaximizeButton(windowElement, maximized) {
  const button = windowElement.querySelector('[data-action="toggle-maximize"]');
  if (!button) {
    return;
  }

  button.textContent = maximized ? "Minimize" : "Expand";
}

function handleKeydown(event) {
  if (event.key === "Escape" && maximizedWindow) {
    restoreWindow(maximizedWindow);
    return;
  }

  if (event.key === "Escape" && activeResizeState) {
    stopWorkspaceResize();
    return;
  }

  if (event.key === "Escape" && activePanelSwapState) {
    stopPanelSwap();
  }
}

function startPanelSwap(event, windowElement, dragHandle) {
  if (
    maximizedWindow ||
    activeResizeState ||
    window.matchMedia("(max-width: 980px)").matches ||
    event.button !== 0 ||
    event.target.closest(".window-action")
  ) {
    return;
  }

  activePanelSwapState = {
    pointerId: event.pointerId,
    sourcePanel: windowElement,
    dragHandle,
    startX: event.clientX,
    startY: event.clientY,
    isDragging: false,
    dropTarget: null,
  };

  dragHandle.setPointerCapture?.(event.pointerId);
  window.addEventListener("pointermove", onPanelSwapMove);
  window.addEventListener("pointerup", stopPanelSwap);
  window.addEventListener("pointercancel", stopPanelSwap);
}

function onPanelSwapMove(event) {
  if (!activePanelSwapState) {
    return;
  }

  const swapState = activePanelSwapState;
  const moveX = event.clientX - swapState.startX;
  const moveY = event.clientY - swapState.startY;
  const distance = Math.hypot(moveX, moveY);

  if (!swapState.isDragging && distance < 8) {
    return;
  }

  if (!swapState.isDragging) {
    swapState.isDragging = true;
    draggedPanel = swapState.sourcePanel;
    swapState.sourcePanel.classList.add("is-dragging-panel");
    document.body.classList.add("is-swapping-panels");
  }

  const nextTarget = findPanelSwapTarget(event.clientX, event.clientY, swapState.sourcePanel);
  if (swapState.dropTarget === nextTarget) {
    return;
  }

  swapState.dropTarget?.classList.remove("is-panel-drop-target");
  swapState.dropTarget = nextTarget;
  swapState.dropTarget?.classList.add("is-panel-drop-target");
}

function findPanelSwapTarget(clientX, clientY, sourcePanel) {
  const hoveredElement = document.elementFromPoint(clientX, clientY);
  const targetPanel = hoveredElement?.closest(".panel-window");
  if (!targetPanel || targetPanel === sourcePanel || !workspace.contains(targetPanel)) {
    return null;
  }
  return targetPanel;
}

function bindWorkspaceResizers() {
  const handles = workspace.querySelectorAll("[data-resize-handle]");
  handles.forEach((handle) => {
    handle.addEventListener("pointerdown", startWorkspaceResize);
  });
}

function startWorkspaceResize(event) {
  if (window.matchMedia("(max-width: 980px)").matches || maximizedWindow) {
    return;
  }

  const handle = event.currentTarget;
  const mode = handle.dataset.resizeHandle;
  if (!mode) {
    return;
  }

  event.preventDefault();
  const rect = workspace.getBoundingClientRect();
  activeResizeState = {
    pointerId: event.pointerId,
    mode,
    rect,
  };
  document.body.classList.add("is-resizing-layout");
  workspace.classList.add("is-resizing-layout");
  handle.setPointerCapture?.(event.pointerId);
  window.addEventListener("pointermove", onWorkspaceResizeMove);
  window.addEventListener("pointerup", stopWorkspaceResize);
  window.addEventListener("pointercancel", stopWorkspaceResize);
}

function onWorkspaceResizeMove(event) {
  if (!activeResizeState) {
    return;
  }

  const { rect, mode } = activeResizeState;
  let nextSplitX = readWorkspaceSplit("--split-x", DEFAULT_LAYOUT_SPLIT_X);
  let nextSplitY = readWorkspaceSplit("--split-y", DEFAULT_LAYOUT_SPLIT_Y);

  if (mode.includes("x")) {
    const minX = (MIN_PANEL_WIDTH_PX / rect.width) * 100;
    const rawSplitX = ((event.clientX - rect.left) / rect.width) * 100;
    nextSplitX = clamp(rawSplitX, minX, 100 - minX);
  }

  if (mode.includes("y")) {
    const minY = (MIN_PANEL_HEIGHT_PX / rect.height) * 100;
    const rawSplitY = ((event.clientY - rect.top) / rect.height) * 100;
    nextSplitY = clamp(rawSplitY, minY, 100 - minY);
  }

  setWorkspaceSplit(nextSplitX, nextSplitY);
}

function stopWorkspaceResize() {
  if (!activeResizeState) {
    return;
  }

  activeResizeState = null;
  document.body.classList.remove("is-resizing-layout");
  workspace.classList.remove("is-resizing-layout");
  window.removeEventListener("pointermove", onWorkspaceResizeMove);
  window.removeEventListener("pointerup", stopWorkspaceResize);
  window.removeEventListener("pointercancel", stopWorkspaceResize);
}

function resetPanelSlots() {
  windows.forEach((windowElement) => {
    const panelId = windowElement.dataset.panelId;
    PANEL_SLOT_CLASSES.forEach((className) => {
      windowElement.classList.remove(className);
    });

    switch (panelId) {
      case "inputs":
        windowElement.classList.add("quadrant-inputs");
        break;
      case "model":
        windowElement.classList.add("quadrant-model");
        break;
      case "results":
        windowElement.classList.add("quadrant-results");
        break;
      case "notes":
        windowElement.classList.add("quadrant-notes");
        break;
      default:
        break;
    }
  });
}

function swapPanelSlots(sourcePanel, targetPanel) {
  const sourceSlot = getPanelSlotClass(sourcePanel);
  const targetSlot = getPanelSlotClass(targetPanel);
  if (!sourceSlot || !targetSlot || sourceSlot === targetSlot) {
    return;
  }

  sourcePanel.classList.remove(sourceSlot);
  targetPanel.classList.remove(targetSlot);
  sourcePanel.classList.add(targetSlot);
  targetPanel.classList.add(sourceSlot);
  syncPanelResizeHandles();
}

function getPanelSlotClass(windowElement) {
  return PANEL_SLOT_CLASSES.find((className) => windowElement.classList.contains(className)) || null;
}

function clearPanelDragState() {
  draggedPanel = null;
  windows.forEach((windowElement) => {
    windowElement.classList.remove("is-dragging-panel", "is-panel-drop-target");
  });
  document.body.classList.remove("is-swapping-panels");
}

function stopPanelSwap() {
  if (!activePanelSwapState) {
    return;
  }

  const { isDragging, sourcePanel, dropTarget } = activePanelSwapState;
  if (isDragging && sourcePanel && dropTarget) {
    swapPanelSlots(sourcePanel, dropTarget);
  }

  activePanelSwapState = null;
  clearPanelDragState();
  window.removeEventListener("pointermove", onPanelSwapMove);
  window.removeEventListener("pointerup", stopPanelSwap);
  window.removeEventListener("pointercancel", stopPanelSwap);
}

function syncPanelResizeHandles() {
  windows.forEach((windowElement) => {
    const slotClass = getPanelSlotClass(windowElement);
    if (!slotClass) {
      return;
    }

    const xHandle = windowElement.querySelector('[data-resize-handle="x"]');
    const yHandle = windowElement.querySelector('[data-resize-handle="y"]');
    const cornerHandle = windowElement.querySelector('[data-resize-handle="xy"]');

    [xHandle, yHandle, cornerHandle].forEach((handle) => {
      if (!handle) {
        return;
      }
      HANDLE_DIRECTION_CLASSES.forEach((className) => {
        handle.classList.remove(className);
      });
    });

    switch (slotClass) {
      case "quadrant-inputs":
        xHandle?.classList.add("panel-resize-handle-right");
        yHandle?.classList.add("panel-resize-handle-bottom");
        cornerHandle?.classList.add("panel-resize-handle-corner-se");
        break;
      case "quadrant-model":
        xHandle?.classList.add("panel-resize-handle-left");
        yHandle?.classList.add("panel-resize-handle-bottom");
        cornerHandle?.classList.add("panel-resize-handle-corner-sw");
        break;
      case "quadrant-results":
        xHandle?.classList.add("panel-resize-handle-right");
        yHandle?.classList.add("panel-resize-handle-top");
        cornerHandle?.classList.add("panel-resize-handle-corner-ne");
        break;
      case "quadrant-notes":
        xHandle?.classList.add("panel-resize-handle-left");
        yHandle?.classList.add("panel-resize-handle-top");
        cornerHandle?.classList.add("panel-resize-handle-corner-nw");
        break;
      default:
        break;
    }
  });
}

function setWorkspaceSplit(splitX, splitY) {
  workspace.style.setProperty("--split-x", `${splitX}%`);
  workspace.style.setProperty("--split-y", `${splitY}%`);
}

function readWorkspaceSplit(propertyName, fallbackValue) {
  const rawValue = getComputedStyle(workspace).getPropertyValue(propertyName).trim();
  const numericValue = Number.parseFloat(rawValue);
  return Number.isFinite(numericValue) ? numericValue : fallbackValue;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function collectFormData() {
  const formData = new FormData(form);
  const payload = {};

  for (const [key, value] of formData.entries()) {
    payload[key] = value;
  }

  return payload;
}

function formatNumber(value, suffix = "", digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "--";
  }

  return `${Number(value).toFixed(digits)}${suffix}`;
}

function formatBool(value) {
  return value ? "Yes" : "No";
}

function formatAiChange(change) {
  return `${change.field_label}: ${formatNumber(change.before_value, ` ${change.units}`)} -> ${formatNumber(change.after_value, ` ${change.units}`)}`;
}

function setStatus(status) {
  const normalized = status || "WAITING";
  elements.statusPill.textContent = normalized.replaceAll("_", " ");
  elements.statusPill.className = "pill";

  if (normalized === "PASS") {
    elements.statusPill.classList.add("pill-pass");
    return;
  }

  if (normalized === "PASS_WITH_WARNINGS" || normalized === "WARNING") {
    elements.statusPill.classList.add("pill-warn");
    return;
  }

  if (normalized === "OUTSIDE_SCOPE") {
    elements.statusPill.classList.add("pill-danger");
    return;
  }

  elements.statusPill.classList.add("pill-neutral");
}

function renderMessages(container, values, emptyMessage) {
  container.innerHTML = "";

  if (!values || values.length === 0) {
    const li = document.createElement("li");
    li.textContent = emptyMessage;
    container.appendChild(li);
    return;
  }

  values.forEach((value) => {
    const li = document.createElement("li");
    li.textContent = value;
    container.appendChild(li);
  });
}

function renderResult(result) {
  latestResult = result;
  setStatus(result.summary?.status);
  elements.governingCheck.textContent = result.summary?.governing_check || "--";
  elements.requiredArea.textContent = formatNumber(result.required_area_sqft, " sf");
  elements.recommendedSize.textContent = `${formatNumber(result.recommended_width_ft, " ft")} x ${formatNumber(result.recommended_length_ft, " ft")}`;
  elements.bearingSummary.textContent = `${formatNumber(result.qmax_ksf, " ksf")} / ${formatNumber(result.input_data?.allowable_bearing_ksf, " ksf")}`;
  elements.eccentricitySummary.textContent = `ex ${formatNumber(result.eccentricity_x_ft, " ft")} | ey ${formatNumber(result.eccentricity_y_ft, " ft")}`;
  elements.qmax.textContent = formatNumber(result.qmax_ksf, " ksf");
  elements.qmin.textContent = formatNumber(result.qmin_ksf, " ksf");
  elements.bearingUtilization.textContent = formatNumber(result.summary?.bearing_utilization, "", 3);
  elements.bearingPass.textContent = formatBool(result.bearing_pass);
  elements.middleThird.textContent = formatBool(result.middle_third_ok);
  elements.fullContact.textContent = formatBool(result.full_contact_ok);
  elements.outsideScope.textContent = formatBool(result.outside_simplified_scope);

  const warnings = (result.warnings || []).map((warning) => `${warning.code}: ${warning.message}`);
  renderMessages(elements.warningsList, warnings, "No warnings.");
  renderMessages(elements.assumptionsList, result.assumptions || [], "No assumptions returned.");

  const preliminaryLine = (result.assumptions || []).find((item) =>
    item.toLowerCase().includes("preliminary only")
  );
  elements.prelimNote.textContent =
    preliminaryLine || "Preliminary only - verify in full design software.";
  viewer.update(result);
}

function renderAiAssistantState(payload = {}) {
  const changes = (payload.applied_changes || []).map(formatAiChange);
  renderMessages(elements.aiChangesList, changes, "No AI changes yet.");
  elements.aiExplanation.textContent =
    payload.explanation || "Waiting for AI suggestion.";
  renderMessages(elements.aiWarningsList, payload.warnings || [], "No AI warnings yet.");
  renderAiCommandStatus(payload, changes);

  if ((changes.length > 0 || (payload.warnings || []).length > 0) && !aiAssistantForm.classList.contains("is-expanded")) {
    setAiAssistantExpanded(true);
  }
}

function renderAiCommandStatus(payload = {}, changes = []) {
  if (!aiCommandStatus) {
    return;
  }

  if (payload.explanation) {
    aiCommandStatus.textContent = payload.explanation;
    aiCommandStatus.classList.toggle("has-warning", (payload.warnings || []).length > 0);
    return;
  }

  if (changes.length > 0) {
    aiCommandStatus.textContent = changes[0];
    aiCommandStatus.classList.remove("has-warning");
    return;
  }

  if (payload.message) {
    aiCommandStatus.textContent = payload.message;
    aiCommandStatus.classList.remove("has-warning");
    return;
  }

  aiCommandStatus.textContent = "Enter a request to update the current footing model.";
  aiCommandStatus.classList.remove("has-warning");
}

function syncFormWithInputData(inputData) {
  if (!inputData) {
    return;
  }

  Object.entries(inputData).forEach(([key, value]) => {
    const field = form.elements.namedItem(key);
    if (!field) {
      return;
    }

    field.value = value === null || value === undefined ? "" : String(value);
  });
}

function setAiLoadingState(isLoading) {
  aiApplyButton.disabled = isLoading;
  aiPromptInput.disabled = isLoading;
  aiLoading.hidden = !isLoading;
}

function renderError(message) {
  latestResult = null;
  setStatus("WARNING");
  elements.governingCheck.textContent = message;
  elements.requiredArea.textContent = "--";
  elements.recommendedSize.textContent = "--";
  elements.bearingSummary.textContent = "--";
  elements.eccentricitySummary.textContent = "--";
  elements.qmax.textContent = "--";
  elements.qmin.textContent = "--";
  elements.bearingUtilization.textContent = "--";
  elements.bearingPass.textContent = "--";
  elements.middleThird.textContent = "--";
  elements.fullContact.textContent = "--";
  elements.outsideScope.textContent = "--";
  renderMessages(elements.warningsList, [message], "No warnings.");
  renderMessages(elements.assumptionsList, [], "No assumptions returned.");
  viewer.update(null);
}

async function calculate() {
  try {
    const response = await fetch("/api/design", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(collectFormData()),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.message || "Calculation failed.");
    }

    renderResult(data);
  } catch (error) {
    renderError(error.message || "Calculation failed.");
  }
}

async function applyAiSuggestion() {
  const userPrompt = aiPromptInput.value.trim();
  if (!userPrompt) {
    renderAiAssistantState({
      explanation: "Enter a request before applying an AI suggestion.",
      warnings: ["AI prompt is required."],
      applied_changes: [],
    });
    return;
  }

  setAiLoadingState(true);

  try {
    const response = await fetch("/api/ai-suggest", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        user_prompt: userPrompt,
        project_data: collectFormData(),
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.message || "AI suggestion failed.");
    }

    syncFormWithInputData(data.updated_input);
    renderResult(data.updated_result);
    renderAiAssistantState(data);
  } catch (error) {
    renderAiAssistantState({
      explanation: "AI suggestion could not be applied.",
      warnings: [error.message || "AI suggestion failed."],
      applied_changes: [],
    });
  } finally {
    setAiLoadingState(false);
  }
}

function scheduleCalculation() {
  window.clearTimeout(debounceTimer);
  debounceTimer = window.setTimeout(calculate, 120);
}
