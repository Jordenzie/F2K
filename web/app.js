const form = document.getElementById("design-form");
const workspace = document.getElementById("workspace");
const viewerContainer = document.getElementById("viewer-3d");
const resetLayoutButton = document.getElementById("reset-layout");
let viewer = {
  update() {},
};

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
};

const windows = [...document.querySelectorAll(".panel-window")];
const splitters = [...document.querySelectorAll(".splitter")];
const slots = [...document.querySelectorAll(".dock-slot")];

const defaultLayout = {
  widthRatio: 0.5,
  heightRatio: 0.54,
};

const defaultSlotByPanel = {
  inputs: "top-left",
  model: "top-right",
  results: "bottom-left",
  notes: "bottom-right",
};

let debounceTimer = null;
let maximizedWindow = null;
const windowPositions = new Map();
let dragState = null;

initializeLayout();

function initializeLayout() {
  initializeViewer();
  resetLayout();
  bindWindowActions();
  bindWindowMaximize();
  bindWindowDrag();
  bindSplitters();
  form.addEventListener("input", scheduleCalculation, { passive: true });
  resetLayoutButton.addEventListener("click", resetLayout);
  window.addEventListener("keydown", handleKeydown);
  window.addEventListener("resize", syncWorkspaceBounds);
  window.addEventListener("load", calculate);
}

async function initializeViewer() {
  try {
    const module = await import("/viewer3d.js");
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

  resetWindowPositions();
  resetWorkspaceSize();
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

function bindWindowDrag() {
  windows.forEach((windowElement) => {
    const handle = windowElement.querySelector("[data-window-handle]");
    handle.addEventListener("pointerdown", (event) => startWindowDrag(event, windowElement));
  });
}

function bindSplitters() {
  splitters.forEach((splitter) => {
    splitter.addEventListener("pointerdown", (event) => startSplitterDrag(event, splitter.dataset.splitter));
  });
}

function startSplitterDrag(event, splitterKey) {
  event.preventDefault();
  const workspaceRect = workspace.getBoundingClientRect();
  const splitter = document.querySelector(`.splitter[data-splitter="${splitterKey}"]`);
  splitter.classList.add("is-active");
  const minPanelWidth = 260;
  const minPanelHeight = 180;

  const onPointerMove = (moveEvent) => {
    if (splitterKey === "vertical") {
      const nextWidth = clamp(moveEvent.clientX - workspaceRect.left, minPanelWidth, workspaceRect.width - minPanelWidth - 8);
      workspace.style.setProperty("--left-width", `${nextWidth}px`);
      return;
    }

    const nextHeight = clamp(moveEvent.clientY - workspaceRect.top, minPanelHeight, workspaceRect.height - minPanelHeight - 8);
    workspace.style.setProperty("--top-height", `${nextHeight}px`);
  };

  const onPointerUp = () => {
    splitter.classList.remove("is-active");
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
  };

  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp);
}

function getWorkspaceWidth() {
  return workspace.getBoundingClientRect().width;
}

function getWorkspaceHeight() {
  return workspace.getBoundingClientRect().height;
}

function resetWorkspaceSize() {
  const width = getWorkspaceWidth();
  const height = getWorkspaceHeight();
  const leftWidth = Math.round(width * defaultLayout.widthRatio);
  const topHeight = Math.round(height * defaultLayout.heightRatio);
  workspace.style.setProperty("--left-width", `${clamp(leftWidth, 260, width - 268)}px`);
  workspace.style.setProperty("--top-height", `${clamp(topHeight, 180, height - 188)}px`);
}

function syncWorkspaceBounds() {
  const width = getWorkspaceWidth();
  const height = getWorkspaceHeight();
  const styles = getComputedStyle(workspace);
  const currentLeft = parseFloat(styles.getPropertyValue("--left-width")) || width * defaultLayout.widthRatio;
  const currentTop = parseFloat(styles.getPropertyValue("--top-height")) || height * defaultLayout.heightRatio;
  workspace.style.setProperty("--left-width", `${clamp(currentLeft, 220, width - 228)}px`);
  workspace.style.setProperty("--top-height", `${clamp(currentTop, 160, height - 168)}px`);
}

function resetWindowPositions() {
  windows.forEach((windowElement) => {
    const panelId = windowElement.dataset.panelId;
    const slotName = defaultSlotByPanel[panelId];
    const slot = workspace.querySelector(`[data-slot="${slotName}"]`);
    if (slot) {
      slot.appendChild(windowElement);
    }
  });
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function startWindowDrag(event, windowElement) {
  if (event.button !== 0) {
    return;
  }

  if (event.target.closest(".window-action") || windowElement.classList.contains("is-maximized")) {
    return;
  }

  const startX = event.clientX;
  const startY = event.clientY;
  let dragging = false;

  const onPointerMove = (moveEvent) => {
    const movedEnough = Math.abs(moveEvent.clientX - startX) > 6 || Math.abs(moveEvent.clientY - startY) > 6;
    if (!dragging && movedEnough) {
      dragging = true;
      dragState = {
        windowElement,
        sourceSlot: windowElement.parentElement,
        targetSlot: null,
      };
      windowElement.classList.add("is-dragging");
      document.body.classList.add("is-dragging-panel");
    }

    if (!dragging) {
      return;
    }

    const targetSlot = findSlotFromPoint(moveEvent.clientX, moveEvent.clientY);
    updateSlotHighlight(targetSlot, dragState.sourceSlot);
    dragState.targetSlot = targetSlot;
  };

  const onPointerUp = () => {
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);

    if (!dragging || !dragState) {
      return;
    }

    const { sourceSlot, targetSlot } = dragState;
    if (targetSlot && targetSlot !== sourceSlot) {
      moveWindowToSlot(windowElement, targetSlot, sourceSlot);
    }

    clearSlotHighlights();
    windowElement.classList.remove("is-dragging");
    document.body.classList.remove("is-dragging-panel");
    dragState = null;
  };

  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp);
}

function findSlotFromPoint(x, y) {
  const candidate = document.elementFromPoint(x, y);
  return candidate?.closest(".dock-slot") || null;
}

function updateSlotHighlight(targetSlot, sourceSlot) {
  slots.forEach((slot) => {
    slot.classList.toggle("is-target", slot === targetSlot && slot !== sourceSlot);
  });
}

function clearSlotHighlights() {
  slots.forEach((slot) => slot.classList.remove("is-target"));
}

function moveWindowToSlot(windowElement, targetSlot, sourceSlot) {
  const occupyingWindow = targetSlot.querySelector(".panel-window");
  if (occupyingWindow) {
    sourceSlot.appendChild(occupyingWindow);
  }
  targetSlot.appendChild(windowElement);
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
  windowElement.classList.add("is-maximized");
  workspace.appendChild(windowElement);
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
  }
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

function renderError(message) {
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

function scheduleCalculation() {
  window.clearTimeout(debounceTimer);
  debounceTimer = window.setTimeout(calculate, 120);
}
