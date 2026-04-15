const form = document.getElementById("design-form");
const workspace = document.getElementById("workspace");
const viewerContainer = document.getElementById("viewer-3d");
const resetLayoutButton = document.getElementById("reset-layout");
const aiAssistantForm = document.getElementById("ai-assistant-form");
const aiPromptInput = document.getElementById("ai-prompt");
const aiApplyButton = document.getElementById("ai-apply-button");
const aiLoading = document.getElementById("ai-loading");
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

initializeLayout();

function initializeLayout() {
  initializeViewer();
  resetLayout();
  bindWindowActions();
  bindWindowMaximize();
  bindAiAssistant();
  form.addEventListener("input", scheduleCalculation, { passive: true });
  resetLayoutButton.addEventListener("click", resetLayout);
  window.addEventListener("keydown", handleKeydown);
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

function bindAiAssistant() {
  if (!aiAssistantForm) {
    return;
  }

  aiAssistantForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await applyAiSuggestion();
  });
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
