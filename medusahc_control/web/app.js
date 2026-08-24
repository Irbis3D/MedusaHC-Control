const app = {
  state: null,
  settings: null,
  stats: null,
  token: localStorage.getItem("medusahc-token") || "",
  confirmCommands: localStorage.getItem("medusahc-confirm-commands") === "true",
  jogStep: Number(localStorage.getItem("medusahc-jog-step")) || 1,
  settingsTool: 0,
  settingsPage: "setup",
  camera: null,
  cameraTimer: null,
  pendingAction: null,
  pendingSetting: null,
  layoutPage: "tuning",
  layoutDraft: [],
  draggedLayoutKey: "",
  reorderPage: "",
  reorderDraft: [],
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));

async function api(path, options = {}) {
  const headers = {"Content-Type": "application/json", ...(options.headers || {})};
  if (app.token) headers["X-Medusa-Token"] = app.token;
  const response = await fetch(path, {...options, headers});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

function toast(message, isError = false) {
  const element = document.createElement("div");
  element.className = `toast${isError ? " error" : ""}`;
  element.textContent = message;
  $("#toast-region").append(element);
  setTimeout(() => element.remove(), 4500);
}

function setView(name) {
  const settingsPage = name === "tuning" ? "tuning" : name === "printer-settings" ? "setup" : "";
  if (app.reorderPage && app.reorderPage !== settingsPage) {
    app.reorderPage = "";
    app.reorderDraft = [];
    updateReorderControls();
  }
  $$(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === name));
  $$(".view").forEach(view => view.classList.toggle("active", view.id === `view-${name}`));
  const labels = {
    overview: ["SYSTEM OVERVIEW", "Toolchanger status"],
    calibration: ["CALIBRATION FUNCTIONS", "Calibration"],
    tuning: ["LIVE PRINT ADJUSTMENTS", "Print tuning"],
    statistics: ["LOCAL HISTORY", "Toolchanger statistics"],
    "printer-settings": ["MACHINE CONFIGURATION", "Printer settings"],
  };
  $("#page-eyebrow").textContent = labels[name][0];
  $("#page-title").textContent = labels[name][1];
  if (name === "tuning") {
    app.settingsPage = "tuning";
    loadSettings();
  }
  if (name === "printer-settings") {
    app.settingsPage = "setup";
    loadSettings();
  }
  if (name === "statistics") loadStats();
  if (name === "overview") scheduleCameraFrame(0);
}

function renderState(state) {
  app.state = state;
  const connected = Boolean(state.connected);
  const error = !connected || state.sensor_error || state.klipper_state === "shutdown";
  $("#connection-dot").className = `status-dot ${connected ? (error ? "error" : "online") : "error"}`;
  $("#connection-label").textContent = connected ? "Moonraker connected" : "Moonraker offline";
  $("#connection-detail").textContent = state.simulated ? "Safe simulation mode" : state.klipper_state;
  $("#mode-chip").textContent = state.simulated ? "SIMULATION" : state.control_enabled ? "LIVE CONTROL" : "LIVE READ ONLY";
  $("#mode-chip").classList.toggle("live", !state.simulated);
  const modeToggle = $("#mode-toggle");
  modeToggle.textContent = state.control_enabled ? "Switch to monitoring" : "Enable control";
  modeToggle.classList.toggle("active", Boolean(state.control_enabled));
  modeToggle.disabled = !state.control_available;

  const banner = $("#state-banner");
  banner.classList.toggle("error", error);
  $("#state-title").textContent = error ? "Attention required" : "MedusaHC is ready";
  $("#state-message").textContent = state.message || "State updated";
  $("#rack-title").textContent = `${state.layout === "rear" ? "Rear" : "Front"} dock layout`;
  $("#fact-axes").textContent = state.homed_axes || "not homed";
  $("#fact-print").textContent = state.print_state || "unknown";
  $("#fact-layout").textContent = state.layout || "unknown";

  renderToolhead(state);
  renderRack(state);
  renderTemperatures(state);
  renderSensors(state);
  renderMotion(state);
  updateActionAvailability(state);
}

function resolvePrinterUrl(url) {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  const path = url.startsWith("/") ? url : `/${url}`;
  return `${window.location.protocol}//${window.location.hostname}${path}`;
}

async function loadCamera(force = false) {
  stopCameraFrames();
  try {
    const camera = await api("/api/camera");
    app.camera = camera;
    const image = $("#camera-stream");
    const empty = $("#camera-empty");
    $("#camera-name").textContent = camera.name || "Printer view";
    if (!camera.available || (!camera.snapshot_url && !camera.stream_url)) {
      image.hidden = true;
      empty.hidden = false;
      return;
    }
    image.style.setProperty("--camera-rotation", `${camera.rotation || 0}deg`);
    image.classList.toggle("flip-x", Boolean(camera.flip_horizontal));
    image.classList.toggle("flip-y", Boolean(camera.flip_vertical));
    $("#camera-frame").style.aspectRatio = String(camera.aspect_ratio || "4 / 3").replace(":", " / ");
    if (camera.snapshot_url) {
      image.dataset.cameraMode = "snapshot";
      image.dataset.cameraUrl = resolvePrinterUrl(camera.snapshot_url);
      if (force) image.removeAttribute("src");
      scheduleCameraFrame(0);
    } else {
      const streamUrl = resolvePrinterUrl(camera.stream_url);
      image.dataset.cameraMode = "stream";
      image.dataset.cameraUrl = streamUrl;
      if (force || image.src !== streamUrl) {
        image.src = `${streamUrl}${streamUrl.includes("?") ? "&" : "?"}_mhc=${Date.now()}`;
      }
    }
  } catch (error) {
    $("#camera-stream").hidden = true;
    $("#camera-empty").hidden = false;
    $("#camera-empty").querySelector("span").textContent = error.message;
  }
}

function stopCameraFrames() {
  if (app.cameraTimer !== null) {
    clearTimeout(app.cameraTimer);
    app.cameraTimer = null;
  }
}

function scheduleCameraFrame(delay = null) {
  stopCameraFrames();
  if (!app.camera?.available || !app.camera?.snapshot_url) return;
  const fps = Math.max(1, Math.min(15, Number(app.camera.target_fps) || 10));
  const frameDelay = delay === null ? Math.round(1000 / fps) : delay;
  app.cameraTimer = setTimeout(requestCameraFrame, frameDelay);
}

function requestCameraFrame() {
  app.cameraTimer = null;
  if (document.hidden || !$("#view-overview").classList.contains("active")) {
    scheduleCameraFrame(1000);
    return;
  }
  const image = $("#camera-stream");
  const url = image.dataset.cameraUrl;
  if (!url) return;
  image.src = `${url}${url.includes("?") ? "&" : "?"}_mhc=${Date.now()}`;
}

function renderMotion(state) {
  const position = state.position || {};
  $("#position-x").textContent = Number(position.x || 0).toFixed(2);
  $("#position-y").textContent = Number(position.y || 0).toFixed(2);
  $("#position-z").textContent = Number(position.z || 0).toFixed(2);
}

function renderToolhead(state) {
  const active = state.tools.find(tool => tool.number === state.current_tool);
  $("#toolhead-name").textContent = active ? active.name : state.current_tool === -1 ? "EMPTY" : "ERROR";
  $("#toolhead-temperature").textContent = active ? `${active.temperature.toFixed(1)} / ${active.target.toFixed(0)} °C` : "—";
  $("#feeder-state").textContent = state.feeder_open ? "Feeder open" : "Feeder closed";
  const feederIndicator = $("#feeder-indicator");
  feederIndicator.classList.toggle("open", Boolean(state.feeder_open));
  $("#feeder-indicator-label").textContent = state.feeder_open ? "OPEN" : "CLOSED";
  $("#quick-tool-number").textContent = active ? active.name : "—";
  $("#quick-tool-copy").textContent = active ? `${active.name} is mounted and ready for manual operations.` : state.message;
}

function renderRack(state) {
  const rack = $("#dock-rack");
  rack.style.setProperty("--tools", Math.max(1, state.tool_count));
  rack.innerHTML = state.tools.map(tool => {
    const sensorClass = tool.active ? "active" : tool.sensor;
    const label = tool.active ? "On toolhead" : tool.sensor === "parked" ? "Parked" : tool.sensor === "released" ? "Missing" : "Unknown";
    return `<article class="dock-card ${escapeHtml(sensorClass)}">
      <div class="dock-tool-icon"></div>
      <strong>${escapeHtml(tool.name)}</strong>
      <small>${escapeHtml(label)} · X ${tool.dock_x.toFixed(1)}</small>
      <button data-select-tool="${tool.number}" ${state.capabilities.can_select && !tool.active ? "" : "disabled"}>${tool.active ? "Active" : "Select tool"}</button>
    </article>`;
  }).join("") || `<p class="muted">No MedusaHC tools were discovered.</p>`;
}

function renderTemperatures(state) {
  const grid = $("#temperature-grid");
  const expected = state.tools.map(tool => String(tool.number)).join(",");
  const rendered = [...grid.querySelectorAll("[data-temp-card]")].map(card => card.dataset.tempCard).join(",");
  if (expected !== rendered) {
    grid.innerHTML = state.tools.map(tool => `<article class="temperature-card" data-temp-card="${tool.number}">
      <div class="temperature-top"><strong>${escapeHtml(tool.name)}</strong><span class="temperature-value" data-temp-current>0.0°</span></div>
      <div class="temperature-target" data-temp-status>Target 0 °C · Power 0%</div>
      <div class="heat-bar" data-temp-power><span></span></div>
      <div class="temperature-controls">
        <input type="text" inputmode="decimal" enterkeyhint="done" autocomplete="off" value="${tool.target || 220}" aria-label="${escapeHtml(tool.name)} target temperature" data-temp-input="${tool.number}">
        <button data-set-temp="${tool.number}">Set</button>
      </div>
    </article>`).join("");
  }
  state.tools.forEach(tool => {
    const card = grid.querySelector(`[data-temp-card="${tool.number}"]`);
    const input = card.querySelector("[data-temp-input]");
    const pending = Number(input.dataset.pendingValue);
    card.querySelector("[data-temp-current]").textContent = `${tool.temperature.toFixed(1)}°`;
    card.querySelector("[data-temp-status]").textContent = `Target ${tool.target.toFixed(0)} °C · Power ${tool.power.toFixed(0)}%`;
    card.querySelector("[data-temp-power]").style.setProperty("--power", `${Math.max(0, Math.min(100, tool.power))}%`);
    card.querySelector("[data-set-temp]").disabled = !state.capabilities.can_heat;
    if (input.dataset.pendingValue && Math.abs(tool.target - pending) < 0.01) {
      delete input.dataset.pendingValue;
      delete input.dataset.edited;
    } else if (document.activeElement !== input && input.dataset.edited !== "true" && !input.dataset.pendingValue && tool.target > 0) {
      input.value = tool.target.toFixed(0);
    }
  });
}

function renderSensors(state) {
  const sensors = Object.keys(state.sensors || {}).length
    ? Object.entries(state.sensors).map(([name, value]) => ({name, value: Number(value), label: name === "e" ? "Toolhead sensor" : `${name.toUpperCase()} dock sensor`}))
    : state.tools.map(tool => ({name: `t${tool.number}`, value: tool.sensor === "parked" ? 1 : tool.active ? 0 : null, label: `${tool.name} dock sensor`}));
  $("#sensor-grid").innerHTML = sensors.map(sensor => `<div class="sensor-chip">
    <span class="sensor-light ${sensor.value === 1 ? "on" : sensor.value === 0 ? "off" : ""}"></span>
    <div><strong>${escapeHtml(sensor.label)}</strong><small>${sensor.value === 1 ? "pressed" : sensor.value === 0 ? "released" : "not exposed"}</small></div>
  </div>`).join("");
}

function updateActionAvailability(state) {
  const mapping = {
    home: "can_home", select_tool: "can_select", drop_tool: "can_drop", clean: "can_clean", test_tools: "can_select",
    feeder_open: "can_feeder", feeder_close: "can_feeder", calibrate_xyz: "can_calibrate",
    calibrate_z: "can_calibrate", calibrate_bed: "can_calibrate", calibrate_z_tilt: "can_calibrate",
    restart_klipper: "can_system", restart_firmware: "can_system", reboot_device: "can_system",
  };
  $$('[data-action]').forEach(button => {
    if (button.dataset.action === "emergency_stop") {
      button.disabled = !state.connected || !state.control_available;
      return;
    }
    button.disabled = !state.capabilities[mapping[button.dataset.action]];
  });
  $$('[data-jog-axis]').forEach(button => button.disabled = !state.capabilities.can_jog);
  $$('[data-home-axis]').forEach(button => button.disabled = !state.capabilities.can_home);
  $("#cool-all").disabled = !state.capabilities.can_heat;
}

async function loadState() {
  try {
    renderState(await api("/api/status"));
  } catch (error) {
    $("#connection-dot").className = "status-dot error";
    $("#connection-label").textContent = "Service offline";
    $("#connection-detail").textContent = error.message;
  }
}

async function runAction(action, payload = {}) {
  const labels = {
    home: "Homing started", home_axis: `Homing ${payload.axis}`, jog: `Moving ${payload.axis}`,
    select_tool: `Selecting T${payload.tool}`, drop_tool: "Parking current tool",
    clean: "Cleaning cycle started", test_tools: "Tool test sequence started", feeder_open: "Opening feeder", feeder_close: "Closing feeder",
    calibrate_xyz: "XYZ calibration started", calibrate_z: "Z calibration started", calibrate_bed: "Bed calibration started", calibrate_z_tilt: "Z Tilt started",
    set_temperature: `Temperature target sent to T${payload.tool}`, emergency_stop: "Emergency stop sent",
    restart_klipper: "Klipper restart requested", restart_firmware: "Firmware restart requested", reboot_device: "Device reboot requested",
  };
  try {
    await api("/api/command", {method: "POST", body: JSON.stringify({action, ...payload})});
    if (action !== "jog") toast(labels[action] || "Command sent");
    setTimeout(loadState, action === "jog" ? 80 : 150);
  } catch (error) {
    toast(error.message, true);
  }
}

async function setControlMode(enabled) {
  try {
    await api("/api/control-mode", {method: "POST", body: JSON.stringify({enabled})});
    toast(enabled ? "Live control enabled" : "Monitoring mode enabled");
    await loadState();
    if ($("#view-tuning").classList.contains("active") || $("#view-printer-settings").classList.contains("active")) await loadSettings();
  } catch (error) {
    toast(error.message, true);
  }
}

const destructiveActions = new Set(["home", "select_tool", "drop_tool", "clean", "test_tools", "feeder_open", "feeder_close", "calibrate_xyz", "calibrate_z", "calibrate_bed", "calibrate_z_tilt", "emergency_stop", "restart_klipper", "restart_firmware", "reboot_device"]);
const alwaysConfirmActions = new Set(["restart_klipper", "restart_firmware", "reboot_device"]);

function confirmAction(action, payload = {}) {
  const copy = {
    select_tool: `The toolhead will move to pick up T${payload.tool}. Keep the movement area clear.`,
    drop_tool: "The toolhead will move to park the current tool.",
    clean: "The active tool will move through the configured prime and brush positions.",
    test_tools: "The TEST_TOOLS macro will check the complete tool rack. Keep the full movement area clear.",
    feeder_open: "The extruder motor will operate the feeder latch.",
    feeder_close: "The extruder motor will operate the feeder latch.",
    home: "The printer will home all axes.",
    home_axis: `The printer will home the ${payload.axis} axis.`,
    calibrate_xyz: "A complete multi-tool XYZ calibration will start. Verify the calibration probe before continuing.",
    calibrate_z: "Tool Z calibration will start. Verify the tap probe and clear the bed.",
    calibrate_bed: "Bed calibration will start. Verify the configured probe.",
    calibrate_z_tilt: "Klipper Z Tilt adjustment will start. Home all axes and verify the probe before continuing.",
    emergency_stop: "Klipper will immediately enter shutdown. Heaters and motion will stop.",
    restart_klipper: "Klipper will restart. Any active print will stop and heaters will be turned off.",
    restart_firmware: "Klipper and all connected MCU firmware will restart. Any active print will stop and heaters will be turned off.",
    reboot_device: "The complete printer computer will reboot. The panel, Moonraker and Klipper will be unavailable while the device starts again.",
  };
  app.pendingSetting = null;
  app.pendingAction = {action, payload};
  const titles = {
    emergency_stop: "Emergency stop?",
    restart_klipper: "Restart Klipper?",
    restart_firmware: "Restart firmware?",
    reboot_device: "Reboot the complete device?",
  };
  $("#dialog-title").textContent = titles[action] || "Confirm printer movement";
  $("#dialog-copy").textContent = copy[action] || "Keep the printer clear.";
  $("#dialog-confirm").textContent = "Continue";
  $("#confirm-dialog").classList.toggle("permanent-warning", alwaysConfirmActions.has(action));
  $("#confirm-dialog").showModal();
}

function confirmPermanentSetting(key) {
  const input = $(`[data-setting-input="${CSS.escape(key)}"]`);
  const definition = app.settings?.schema?.find(item => item.key === key);
  if (!input || !definition || definition.available === false) return;
  const target = definition.kind === "tool_offset" ? "saved_vars.cfg" : "MHC_variables.cfg";
  app.pendingAction = null;
  app.pendingSetting = {key, value: input.value};
  $("#dialog-title").textContent = "Save permanent value?";
  $("#dialog-copy").textContent = `${definition.label} will be permanently changed to ${input.value} in ${target}. This value will be used after future restarts.`;
  $("#dialog-confirm").textContent = "Save to config";
  $("#confirm-dialog").classList.add("permanent-warning");
  $("#confirm-dialog").showModal();
}

async function loadSettings() {
  try {
    app.settings = await api("/api/settings");
    renderSettings(app.settings);
  } catch (error) { toast(error.message, true); }
}

function renderSettings(payload) {
  const reorderEnabled = app.reorderPage === app.settingsPage;
  const reorderOrder = new Map(
    (reorderEnabled ? app.reorderDraft : []).map(item => [item.layout_key, Number(item.order || 0)])
  );
  const generalGroups = {};
  const pageDefinitions = payload.schema
    .filter(item => item.page === app.settingsPage && item.visible !== false)
    .sort((left, right) => (
      (reorderOrder.get(left.layout_key) ?? Number(left.layout_order || 0))
      - (reorderOrder.get(right.layout_key) ?? Number(right.layout_order || 0))
    ));
  const toolDefinitions = pageDefinitions.filter(item => Number.isInteger(item.tool));
  pageDefinitions.filter(item => !Number.isInteger(item.tool)).forEach(definition => (generalGroups[definition.group] ||= []).push(definition));
  const tools = [...new Set(toolDefinitions.map(item => item.tool))];
  if (!tools.includes(app.settingsTool)) app.settingsTool = tools[0] || 0;
  const runtimeAvailable = Boolean(app.state?.control_enabled && app.state?.connected && app.state?.klipper_state === "ready");
  const fileAvailable = Boolean(runtimeAvailable && app.state?.capabilities?.can_edit && payload.file_write_available);
  const row = definition => {
    const available = definition.available !== false;
    const value = available ? payload.values[definition.key] ?? "" : "";
    const history = payload.history?.[definition.key] || [];
    const setupLocked = definition.page === "setup" && ["printing", "paused"].includes(app.state?.print_state);
    const runtimeDisabled = available && runtimeAvailable && !setupLocked ? "" : "disabled";
    const fileDisabled = available && fileAvailable && !setupLocked ? "" : "disabled";
    const hasConfiguredValue = definition.configured_value !== undefined && definition.configured_value !== null && Number.isFinite(Number(definition.configured_value));
    const resetDisabled = available && runtimeAvailable && !setupLocked && hasConfiguredValue ? "" : "disabled";
    const inputDisabled = available ? "" : "disabled";
    const minimum = definition.min === undefined ? "" : ` min="${escapeHtml(definition.min)}"`;
    const maximum = definition.max === undefined ? "" : ` max="${escapeHtml(definition.max)}"`;
    const input = definition.type === "choice"
      ? `<select data-setting-input="${escapeHtml(definition.key)}" ${inputDisabled}>${definition.choices.map(choice => `<option value="${choice.value}" ${Number(value) === Number(choice.value) ? "selected" : ""}>${escapeHtml(choice.label)}</option>`).join("")}</select>`
      : `<input data-setting-input="${escapeHtml(definition.key)}" type="number" inputmode="decimal" value="${escapeHtml(value)}"${minimum}${maximum} step="${definition.step || 0.1}" placeholder="${available ? "" : "Variable not found"}" ${inputDisabled}>`;
    const historyPanel = `<details class="setting-history"><summary>Recent values <span>${history.length}/10</span></summary><div>${history.length ? history.map(item => `<button type="button" data-history-key="${escapeHtml(definition.key)}" data-history-value="${escapeHtml(item.value)}"><strong>${escapeHtml(item.value)}</strong><span>${item.mode === "permanent" ? "Config" : "Applied"} · ${new Date(item.created_at * 1000).toLocaleString()}</span></button>`).join("") : `<p>No values entered through the panel yet.</p>`}</div></details>`;
    const description = definition.description ? `<div class="setting-tooltip" role="tooltip">${escapeHtml(definition.description).replaceAll("\n", "<br>")}</div>` : "";
    const variableName = escapeHtml(definition.variable || definition.label);
    const variableHeader = definition.description
      ? `<div class="setting-variable-header"><button type="button" class="setting-variable-help" data-setting-help aria-expanded="false"><span>${variableName}</span><span class="setting-help-mark" aria-hidden="true">?</span></button><span class="setting-unit">${escapeHtml(definition.unit || "")}</span>${description}</div>`
      : `<div class="setting-variable-header"><span class="setting-variable-name">${variableName}</span><span class="setting-unit">${escapeHtml(definition.unit || "")}</span></div>`;
    const unavailable = available ? "" : `<p class="setting-unavailable"><strong>Variable not found.</strong><span>${escapeHtml(definition.availability_reason || definition.variable)}</span></p>`;
    const configuredChoice = definition.type === "choice"
      ? definition.choices.find(choice => Number(choice.value) === Number(definition.configured_value))
      : null;
    const configuredLabel = configuredChoice?.label ?? definition.configured_value;
    const temporaryValueActive = hasConfiguredValue && value !== "" && Number(value) !== Number(definition.configured_value);
    const configured = hasConfiguredValue ? `<p class="configured-value ${temporaryValueActive ? "changed" : ""}">${temporaryValueActive ? "Temporary value active · " : ""}Saved config: <strong>${escapeHtml(configuredLabel)}</strong></p>` : "";
    const reorderAttributes = reorderEnabled ? ` draggable="true" aria-grabbed="false"` : "";
    return `<div class="setting-row ${available ? "" : "setting-row-unavailable"} ${reorderEnabled ? "reorder-enabled" : ""}"${reorderAttributes} data-layout-key="${escapeHtml(definition.layout_key)}">${variableHeader}<div class="setting-control">${input}<button data-setting-mode="runtime" data-setting-key="${escapeHtml(definition.key)}" ${runtimeDisabled}>Apply</button><button class="reset" data-setting-reset="${escapeHtml(definition.key)}" title="Apply the value currently stored in the printer configuration" ${resetDisabled}>Reset</button><button class="permanent" data-setting-mode="permanent" data-setting-key="${escapeHtml(definition.key)}" ${fileDisabled}>Save to config</button></div>${configured}${unavailable}${historyPanel}</div>`;
  };
  const groupDescriptions = {
    "Cleaning and priming": "Shared machine positions used by every tool during priming and brush moves.",
    Motion: "Global speeds and acceleration used throughout the complete toolchange sequence.",
    Layout: "Direction and Y positions that define how the rack is approached.",
    Feeder: "Latch movement and motor current for opening and closing the feeder.",
    Calibration: "Shared correction values used by the calibration macros.",
    "Dock coordinates": "Exact X parking position for every installed tool.",
    "Shared Priming": "Legacy priming values shared by every tool in this configuration.",
    "Shared First Prime": "Legacy first-prime values shared by every tool in this configuration.",
    "Shared Cleaning": "Legacy cleaning values shared by every tool in this configuration.",
  };
  const general = Object.entries(generalGroups).map(([group, definitions]) => `<section class="settings-group settings-group-${app.settingsPage}"><div class="settings-group-heading"><div><span class="kicker">${app.settingsPage === "setup" ? "PRINTER" : "GLOBAL"}</span><h3>${escapeHtml(group)}</h3></div><p>${escapeHtml(groupDescriptions[group] || "")}</p></div><div class="settings-grid">${definitions.map(row).join("")}</div></section>`).join("");
  const selected = toolDefinitions.filter(item => item.tool === app.settingsTool);
  const categories = {};
  selected.forEach(definition => (categories[definition.category || "Tool"] ||= []).push(definition));
  const categoryDescriptions = {
    Priming: "Extrusion and retract values used before this tool starts printing.",
    "First Prime": "Optional initial extrusion used the first time this tool enters the print.",
    Cleaning: "Brush pattern, cleaning speed and final retract for this tool.",
    Offsets: "XYZ correction applied when this tool is mounted.",
  };
  const discoveryWarning = payload.discovery_warning ? `<section class="setup-warning settings-discovery-warning"><strong>Variables unavailable</strong><span>${escapeHtml(payload.discovery_warning)}</span></section>` : "";
  const toolPanel = tools.length ? `<section class="settings-group tool-settings-group"><div class="tool-settings-heading"><div><span class="kicker">SELECT ACTIVE PROFILE</span><h3>Tool-specific tuning</h3><p>Only the selected tool is shown below.</p></div><div class="tool-tabs" aria-label="Tool profile">${tools.map(tool => `<button class="${tool === app.settingsTool ? "active" : ""}" data-settings-tool="${tool}">T${tool}</button>`).join("")}</div></div><div class="selected-tool-banner"><strong>T${app.settingsTool}</strong><span>Editing priming, cleaning and offset values for tool T${app.settingsTool}</span></div><div class="tuning-category-grid">${Object.entries(categories).map(([category, definitions]) => `<section class="setting-category category-${category.toLowerCase().replaceAll(" ", "-")}"><div class="setting-category-heading"><div><span class="category-marker"></span><h4>${escapeHtml(category)}</h4></div><p>${escapeHtml(categoryDescriptions[category] || "")}</p></div><div class="settings-grid">${definitions.map(row).join("")}</div></section>`).join("")}</div></section>` : "";
  if (app.settingsPage === "tuning") {
    const sharedTuning = general ? `<div class="global-tuning-groups">${general}</div>` : "";
    $("#tuning-groups").innerHTML = `${discoveryWarning}<section class="tuning-guide"><div class="guide-apply"><strong>Apply</strong><span>Changes the running value immediately and resets after restart.</span></div><div class="guide-reset"><strong>Reset</strong><span>Restores the currently saved configuration value without writing a file.</span></div><div class="guide-save"><strong>Save to config</strong><span>Permanently replaces the stored value after confirmation.</span></div></section>${toolPanel}${sharedTuning}`;
  } else {
    $("#printer-settings-groups").innerHTML = `${discoveryWarning}<section class="setup-warning"><strong>Idle printer required</strong><span>Permanent changes require confirmation. Verify dock movement at low speed after changing geometry.</span></section>${general}`;
  }
}

function layoutCandidates(payload = app.settings) {
  const candidates = new Map();
  for (const definition of payload?.schema || []) {
    const key = String(definition.layout_key || "");
    if (!key) continue;
    const existing = candidates.get(key);
    if (!existing) {
      candidates.set(key, {
        layout_key: key,
        page: definition.page,
        group: definition.category || definition.group || "Other",
        macro: /^TOOL_STATE_\d+$/.test(definition.macro) ? "TOOL_STATE_*" : definition.macro,
        variable: definition.variable,
        available: definition.available !== false,
        default_visible: definition.default_visible !== false,
        visible: definition.visible !== false,
        description: definition.description || "",
        order: Number(definition.layout_order || 0),
      });
      continue;
    }
    existing.available ||= definition.available !== false;
    existing.default_visible ||= definition.default_visible !== false;
    existing.visible ||= definition.visible !== false;
    if (!existing.description && definition.description) existing.description = definition.description;
    existing.order = Math.min(existing.order, Number(definition.layout_order || 0));
  }
  return [...candidates.values()].sort((left, right) => left.order - right.order);
}

function buildLayoutDraft() {
  return layoutCandidates().map(item => ({...item}));
}

function openSettingsLayout(page) {
  if (!app.settings) return toast("Settings are still loading", true);
  app.layoutPage = page;
  app.layoutDraft = buildLayoutDraft();
  $("#layout-dialog-title").textContent = page === "tuning" ? "Customize print tuning" : "Customize printer settings";
  $("#layout-search").value = "";
  renderLayoutEditor();
  $("#settings-layout-dialog").showModal();
}

function renderLayoutEditor() {
  const search = $("#layout-search").value.trim().toLowerCase();
  const items = app.layoutDraft
    .filter(item => item.page === app.layoutPage && (item.available || item.visible))
    .filter(item => !search || `${item.variable} ${item.macro} ${item.group} ${item.description}`.toLowerCase().includes(search))
    .sort((left, right) => left.order - right.order || left.variable.localeCompare(right.variable));
  $("#layout-variable-list").innerHTML = items.length ? items.map(item => `
    <div class="layout-variable-item ${item.available ? "" : "unavailable"}" data-layout-item="${escapeHtml(item.layout_key)}">
      <input type="checkbox" data-layout-visible="${escapeHtml(item.layout_key)}" ${item.visible ? "checked" : ""}>
      <div class="layout-variable-name">
        <strong>${escapeHtml(item.variable)}</strong>
        <span>${escapeHtml(item.macro)} &middot; ${escapeHtml(item.group)}</span>
        ${item.available ? "" : "<em>Variable not found in the current configuration</em>"}
      </div>
      <textarea data-layout-description="${escapeHtml(item.layout_key)}" rows="2" placeholder="Optional local description">${escapeHtml(item.description)}</textarea>
    </div>`).join("") : `<p class="muted">No matching variables were found.</p>`;
}

function visibleLayoutEntries(draft = app.layoutDraft) {
  return draft
    .filter(item => item.visible)
    .sort((left, right) => left.order - right.order)
    .map(item => ({layout_key: item.layout_key, description: item.description || ""}));
}

async function saveSettingsLayout(entries = null, closeDialog = true) {
  try {
    await api("/api/settings/layout", {
      method: "POST",
      body: JSON.stringify({entries: entries || visibleLayoutEntries()}),
    });
    if (closeDialog && $("#settings-layout-dialog").open) $("#settings-layout-dialog").close();
    toast("Variable layout saved");
    await loadSettings();
  } catch (error) { toast(error.message, true); }
}

async function resetSettingsLayout() {
  try {
    await api("/api/settings/layout/reset", {method: "POST", body: "{}"});
    $("#settings-layout-dialog").close();
    toast("Automatic variable layout restored");
    await loadSettings();
  } catch (error) { toast(error.message, true); }
}

function updateReorderControls() {
  $$('[data-reorder-settings]').forEach(button => {
    const active = app.reorderPage === button.dataset.reorderSettings;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.textContent = active ? "Save order" : "Reorder variables";
  });
  $$('[data-cancel-reorder]').forEach(button => {
    button.hidden = app.reorderPage !== button.dataset.cancelReorder;
  });
  $$('[data-customize-settings]').forEach(button => {
    button.disabled = app.reorderPage === button.dataset.customizeSettings;
  });
}

function clearReorderState() {
  app.reorderPage = "";
  app.reorderDraft = [];
  app.draggedLayoutKey = "";
  $$(".dragging, .drag-target").forEach(item => item.classList.remove("dragging", "drag-target"));
  updateReorderControls();
}

function startReorderMode(page) {
  app.reorderPage = page;
  app.reorderDraft = buildLayoutDraft();
  app.draggedLayoutKey = "";
  updateReorderControls();
  if (app.settings && app.settingsPage === page) renderSettings(app.settings);
  toast("Reorder mode enabled. Changes are not saved until Save order is pressed.");
}

async function finishReorderMode(page) {
  if (app.reorderPage !== page) return startReorderMode(page);
  const entries = visibleLayoutEntries(app.reorderDraft);
  try {
    await api("/api/settings/layout", {
      method: "POST",
      body: JSON.stringify({entries}),
    });
    clearReorderState();
    toast("Variable order saved");
    await loadSettings();
  } catch (error) { toast(error.message, true); }
}

function cancelReorderMode(page, notify = true) {
  if (app.reorderPage !== page) return;
  clearReorderState();
  if (app.settings && app.settingsPage === page) renderSettings(app.settings);
  if (notify) toast("Reordering cancelled. The saved order was not changed.");
}

function toggleReorderMode(page) {
  return app.reorderPage === page ? finishReorderMode(page) : startReorderMode(page);
}

function captureRenderedOrder(grid) {
  const page = grid.closest("#view-tuning") ? "tuning" : "setup";
  const orderedKeys = $$(`[data-layout-key]`, grid).map(item => item.dataset.layoutKey);
  const draft = app.reorderDraft.map(item => ({...item}));
  const visibleOnPage = draft
    .filter(item => item.page === page && item.visible)
    .sort((left, right) => left.order - right.order);
  const gridKeys = new Set(orderedKeys);
  let gridIndex = 0;
  const completeOrder = visibleOnPage.map(item => (
    gridKeys.has(item.layout_key) ? orderedKeys[gridIndex++] : item.layout_key
  ));
  const rank = new Map(completeOrder.map((key, index) => [key, index]));
  for (const item of draft) {
    if (item.page === page && item.visible) item.order = rank.get(item.layout_key) ?? completeOrder.length;
  }
  app.reorderDraft = draft;
}

async function changeSetting(key, mode, suppliedValue = null) {
  const input = $(`[data-setting-input="${CSS.escape(key)}"]`);
  const definition = app.settings?.schema?.find(item => item.key === key);
  if (!input || !definition || definition.available === false) return;
  try {
    const value = suppliedValue === null ? input.value : suppliedValue;
    const result = await api("/api/settings", {method: "POST", body: JSON.stringify({key, value, mode})});
    const label = {runtime: "applied", permanent: "saved to config"}[result.mode] || "updated";
    toast(`${key} ${label}: ${result.value}`);
    app.settings.values ||= {};
    app.settings.history ||= {};
    app.settings.values[key] = result.value;
    if (result.mode === "permanent") definition.configured_value = result.value;
    const history = app.settings.history[key] ||= [];
    history.unshift({value: result.value, mode: result.mode, created_at: Date.now() / 1000});
    app.settings.history[key] = history.slice(0, 10);
    renderSettings(app.settings);
    setTimeout(loadState, 180);
  } catch (error) { toast(error.message, true); }
}

async function loadStats() {
  try {
    app.stats = await api("/api/stats");
    renderStats(app.stats);
  } catch (error) { toast(error.message, true); }
}

function renderStats(stats) {
  const total = Number(stats.totals.tool_pickup || 0) + Number(stats.totals.tool_park || 0);
  const cards = [
    ["Completed actions", total], ["Tool pickups", stats.totals.tool_pickup || 0],
    ["Tools parked", stats.totals.tool_park || 0], ["Failed changes", stats.totals.toolchange_failed || 0],
  ];
  $("#stats-since").textContent = `Counting since ${new Date(stats.started_at * 1000).toLocaleString()}`;
  $("#stat-cards").innerHTML = cards.map(([label, value]) => `<div class="stat-card"><span>${escapeHtml(label)}</span><strong>${value}</strong></div>`).join("");
  $("#tool-stats").innerHTML = stats.per_tool.length ? stats.per_tool.map(item => `<div class="tool-stat-row"><div class="tool-stat-id">T${item.tool}</div><div class="tool-stat-values"><div><span>Pickups</span><strong>${item.pickups}</strong></div><div><span>Parks</span><strong>${item.parks}</strong></div><div><span>Errors</span><strong>${item.errors}</strong></div></div></div>`).join("") : `<p class="muted">No tool activity recorded yet.</p>`;
  $("#event-list").innerHTML = stats.recent.length ? stats.recent.map(item => {
    const names = {tool_pickup: "Tool picked up", tool_park: "Tool parked", toolchange_failed: "Toolchange failed"};
    const detail = names[item.event_type] || item.event_type.replaceAll("_", " ");
    return `<div class="event-row"><span class="event-mark ${item.success ? "" : "error"}"></span><div><strong>${escapeHtml(detail)}</strong><small>${item.tool == null ? "MedusaHC" : `Tool T${item.tool}`}</small></div><time>${new Date(item.created_at * 1000).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})}</time></div>`;
  }).join("") : `<p class="muted">The local event log is empty.</p>`;
}

document.addEventListener("click", event => {
  const settingHelp = event.target.closest("[data-setting-help]");
  const openHelpRow = settingHelp?.closest(".setting-row");
  $$(".setting-row.tooltip-open").forEach(row => {
    if (row !== openHelpRow) {
      row.classList.remove("tooltip-open");
      row.querySelector("[data-setting-help]")?.setAttribute("aria-expanded", "false");
    }
  });
  if (settingHelp) {
    const expanded = openHelpRow.classList.toggle("tooltip-open");
    settingHelp.setAttribute("aria-expanded", String(expanded));
    return;
  }
  const nav = event.target.closest("[data-view]");
  if (nav) return setView(nav.dataset.view);
  const customizeSettings = event.target.closest("[data-customize-settings]");
  if (customizeSettings) return openSettingsLayout(customizeSettings.dataset.customizeSettings);
  const reorderSettings = event.target.closest("[data-reorder-settings]");
  if (reorderSettings) return toggleReorderMode(reorderSettings.dataset.reorderSettings);
  const cancelReorder = event.target.closest("[data-cancel-reorder]");
  if (cancelReorder) return cancelReorderMode(cancelReorder.dataset.cancelReorder);
  const select = event.target.closest("[data-select-tool]");
  if (select) {
    const payload = {tool: Number(select.dataset.selectTool)};
    return app.confirmCommands ? confirmAction("select_tool", payload) : runAction("select_tool", payload);
  }
  const jog = event.target.closest("[data-jog-axis]");
  if (jog) {
    const axis = jog.dataset.jogAxis;
    const direction = Number(jog.dataset.jogDirection);
    const speed = Number(axis === "Z" ? $("#z-jog-speed").value : $("#xy-jog-speed").value);
    return runAction("jog", {axis, distance: app.jogStep * direction, speed});
  }
  const homeAxis = event.target.closest("[data-home-axis]");
  if (homeAxis) {
    const payload = {axis: homeAxis.dataset.homeAxis};
    return app.confirmCommands ? confirmAction("home_axis", payload) : runAction("home_axis", payload);
  }
  const step = event.target.closest("[data-jog-step]");
  if (step) {
    app.jogStep = Number(step.dataset.jogStep);
    localStorage.setItem("medusahc-jog-step", String(app.jogStep));
    $$('[data-jog-step]').forEach(button => button.classList.toggle("active", Number(button.dataset.jogStep) === app.jogStep));
    return;
  }
  const heat = event.target.closest("[data-set-temp]");
  if (heat) {
    const tool = Number(heat.dataset.setTemp);
    const input = $(`[data-temp-input="${tool}"]`);
    const temperature = Number(String(input.value).replace(",", "."));
    if (!Number.isFinite(temperature) || temperature < 0 || temperature > 290) {
      return toast("Temperature must be between 0 and 290 °C", true);
    }
    input.dataset.pendingValue = String(temperature);
    input.dataset.edited = "true";
    return runAction("set_temperature", {tool, temperature});
  }
  const settingsTool = event.target.closest("[data-settings-tool]");
  if (settingsTool) {
    app.settingsTool = Number(settingsTool.dataset.settingsTool);
    return renderSettings(app.settings);
  }
  const setting = event.target.closest("[data-setting-mode]");
  if (setting) {
    return setting.dataset.settingMode === "permanent"
      ? confirmPermanentSetting(setting.dataset.settingKey)
      : changeSetting(setting.dataset.settingKey, "runtime");
  }
  const resetSetting = event.target.closest("[data-setting-reset]");
  if (resetSetting) {
    const definition = app.settings?.schema?.find(item => item.key === resetSetting.dataset.settingReset);
    if (!definition || definition.configured_value === undefined || definition.configured_value === null) return;
    return changeSetting(definition.key, "runtime", definition.configured_value);
  }
  const historyValue = event.target.closest("[data-history-value]");
  if (historyValue) {
    const input = $(`[data-setting-input="${CSS.escape(historyValue.dataset.historyKey)}"]`);
    if (input) input.value = historyValue.dataset.historyValue;
    historyValue.closest("details")?.removeAttribute("open");
    return;
  }
  const action = event.target.closest("[data-action]");
  if (action && destructiveActions.has(action.dataset.action)) {
    return app.confirmCommands || alwaysConfirmActions.has(action.dataset.action)
      ? confirmAction(action.dataset.action)
      : runAction(action.dataset.action);
  }
});

document.addEventListener("change", event => {
  const visibility = event.target.closest("[data-layout-visible]");
  if (!visibility) return;
  const item = app.layoutDraft.find(candidate => candidate.layout_key === visibility.dataset.layoutVisible);
  if (item) item.visible = Boolean(visibility.checked);
});

document.addEventListener("input", event => {
  const description = event.target.closest("[data-layout-description]");
  if (description) {
    const item = app.layoutDraft.find(candidate => candidate.layout_key === description.dataset.layoutDescription);
    if (item) item.description = description.value;
    return;
  }
  if (event.target === $("#layout-search")) renderLayoutEditor();
});

document.addEventListener("dragstart", event => {
  const row = event.target.closest("[data-layout-key]");
  if (!row || !app.reorderPage || !row.classList.contains("reorder-enabled") || event.target.closest("input, select, button, details, summary")) return event.preventDefault();
  app.draggedLayoutKey = row.dataset.layoutKey;
  row.classList.add("dragging");
  row.setAttribute("aria-grabbed", "true");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", app.draggedLayoutKey);
});

document.addEventListener("dragover", event => {
  const row = event.target.closest("[data-layout-key]");
  const dragged = document.querySelector(`[data-layout-key="${CSS.escape(app.draggedLayoutKey)}"].dragging`);
  if (!row || !dragged || row === dragged || row.parentElement !== dragged.parentElement) return;
  event.preventDefault();
  $$(".drag-target").forEach(item => item.classList.remove("drag-target"));
  row.classList.add("drag-target");
  const after = event.clientY > row.getBoundingClientRect().top + row.offsetHeight / 2;
  row.parentElement.insertBefore(dragged, after ? row.nextSibling : row);
});

document.addEventListener("drop", event => {
  if (!app.reorderPage) return;
  const dragged = $(".setting-row.dragging");
  if (!dragged) return;
  event.preventDefault();
  const grid = dragged.parentElement;
  dragged.classList.remove("dragging");
  dragged.setAttribute("aria-grabbed", "false");
  $$(".drag-target").forEach(item => item.classList.remove("drag-target"));
  app.draggedLayoutKey = "";
  captureRenderedOrder(grid);
});

document.addEventListener("dragend", () => {
  $$(".dragging, .drag-target").forEach(item => {
    item.classList.remove("dragging", "drag-target");
    if (item.hasAttribute("aria-grabbed")) item.setAttribute("aria-grabbed", "false");
  });
  app.draggedLayoutKey = "";
});

$("#mode-toggle").addEventListener("click", () => {
  if (!app.state?.control_available) return;
  return setControlMode(!app.state.control_enabled);
});

$("#confirm-toggle").checked = app.confirmCommands;
$$('[data-jog-step]').forEach(button => button.classList.toggle("active", Number(button.dataset.jogStep) === app.jogStep));
$("#xy-jog-speed").addEventListener("input", event => $("#xy-speed-label").textContent = `${event.target.value} mm/s`);
$("#z-jog-speed").addEventListener("input", event => $("#z-speed-label").textContent = `${event.target.value} mm/s`);
$("#confirm-toggle").addEventListener("change", event => {
  app.confirmCommands = Boolean(event.target.checked);
  localStorage.setItem("medusahc-confirm-commands", String(app.confirmCommands));
  toast(app.confirmCommands ? "Command confirmations enabled" : "Commands will be sent immediately");
});

document.addEventListener("input", event => {
  if (event.target.matches("[data-temp-input]")) event.target.dataset.edited = "true";
});

$("#save-settings-layout").addEventListener("click", () => saveSettingsLayout());
$("#reset-settings-layout").addEventListener("click", resetSettingsLayout);

$("#cool-all").addEventListener("click", async () => {
  if (!app.state) return;
  for (const tool of app.state.tools) await runAction("set_temperature", {tool: tool.number, temperature: 0});
});

$("#camera-refresh").addEventListener("click", () => loadCamera(true));
$("#camera-stream").addEventListener("load", event => {
  const image = event.currentTarget;
  image.hidden = false;
  $("#camera-empty").hidden = true;
  if (image.naturalWidth && image.naturalHeight) {
    $("#camera-frame").style.aspectRatio = `${image.naturalWidth} / ${image.naturalHeight}`;
  }
  if (image.dataset.cameraMode === "snapshot") scheduleCameraFrame();
});
$("#camera-stream").addEventListener("error", event => {
  const image = event.currentTarget;
  if (image.hidden) {
    $("#camera-empty").hidden = false;
    $("#camera-empty").querySelector("span").textContent = "Camera is reconnecting automatically.";
  }
  if (image.dataset.cameraMode === "snapshot") scheduleCameraFrame(1200);
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopCameraFrames();
  else scheduleCameraFrame(0);
});

$("#reset-stats").addEventListener("click", async () => {
  try {
    await api("/api/stats/reset", {method: "POST", body: "{}"});
    toast("Toolchange statistics reset");
    await loadStats();
  } catch (error) { toast(error.message, true); }
});

$("#token-button").addEventListener("click", () => {
  const value = window.prompt("MedusaHC control token. Leave empty when token protection is disabled.", app.token);
  if (value === null) return;
  app.token = value.trim();
  localStorage.setItem("medusahc-token", app.token);
  toast(app.token ? "Control token stored in this browser" : "Control token cleared");
});

$("#confirm-dialog").addEventListener("close", event => {
  if (event.target.returnValue === "confirm" && app.pendingAction) {
    const {action, payload} = app.pendingAction;
    app.pendingAction = null;
    runAction(action, payload);
  } else if (event.target.returnValue === "confirm" && app.pendingSetting) {
    const {key, value} = app.pendingSetting;
    app.pendingSetting = null;
    changeSetting(key, "permanent", value);
  } else {
    app.pendingAction = null;
    app.pendingSetting = null;
  }
});

loadState();
loadStats();
loadCamera();
setInterval(loadState, 900);
setInterval(() => { if ($("#view-statistics").classList.contains("active")) loadStats(); }, 5000);
