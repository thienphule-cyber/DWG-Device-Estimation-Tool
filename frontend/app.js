"use strict";

// Colors used for device types in the preview and legend
const TYPE_COLORS = {
  lighting: "#f59e0b",
  switches: "#3b82f6",
  sockets: "#10b981",
  sensors: "#ef4444",
  hvac: "#8b5cf6",
};
const TYPE_LABELS = {
  lighting: "Lighting",
  switches: "Switches",
  sockets: "Sockets",
  sensors: "Sensors",
  hvac: "HVAC",
};
const LOW_CONFIDENCE = 0.5;
const SVG_NS = "http://www.w3.org/2000/svg";

// Server response: { result, room_types, device_types }
let state = null;

const $ = (id) => document.getElementById(id);

// ---------- Small DOM helpers (use DOM APIs so CAD text is never parsed as HTML) ----------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value !== null && value !== undefined) node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function setStatus(message, kind = "") {
  const node = $("status");
  node.textContent = message;
  node.className = "status " + kind;
}

// ---------- API ----------

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let data = null;
  try {
    data = await response.json();
  } catch (_) {
    // Non-JSON response, handled below
  }
  if (!response.ok) {
    throw new Error((data && data.error) || `Request failed (${response.status})`);
  }
  return data;
}

async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  setStatus(`Analyzing ${file.name} ...`, "busy");
  $("upload-btn").disabled = true;
  try {
    state = await api("/upload", { method: "POST", body: form });
    setStatus(`Done: ${file.name}`);
    render();
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    $("upload-btn").disabled = false;
    $("file-input").value = ""; // allow uploading the same file again
  }
}

async function sendUpdate(payload) {
  const scrollY = window.scrollY;
  try {
    state = await api("/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    render();
    window.scrollTo(0, scrollY);
    setStatus("Saved");
  } catch (err) {
    setStatus(err.message, "error");
  }
}

async function loadExisting() {
  try {
    state = await api("/results");
    render();
  } catch (_) {
    // No analysis yet, keep the empty state
  }
}

// ---------- Rendering ----------

function render() {
  const hasResult = Boolean(state && state.result);
  $("export-btn").disabled = !hasResult;
  $("empty").hidden = hasResult;
  $("content").hidden = !hasResult;
  if (!hasResult) return;

  renderWarnings();
  renderSummary();
  renderPreview();
  renderRooms();
}

function renderWarnings() {
  const box = $("warnings");
  const warnings = state.result.warnings || [];
  box.replaceChildren();
  box.hidden = warnings.length === 0;
  if (!warnings.length) return;
  box.append(el("strong", {}, "Warnings"), el("ul", {}, warnings.map((w) => el("li", {}, w))));
}

function renderSummary() {
  const { rooms, estimates } = state.result;
  const sum = (key) => estimates.reduce((acc, e) => acc + e[key], 0);
  const zones = new Set(rooms.map((r) => r.zone));
  const stats = [
    ["Zones", zones.size],
    ["Rooms", rooms.length],
    ["Detected", sum("detected")],
    ["Estimated", sum("estimated")],
    ["Recommended", sum("recommended")],
    ["Total", sum("total")],
  ];
  $("summary").replaceChildren(
    ...stats.map(([label, value]) =>
      el("div", { class: "stat" }, el("div", { class: "value" }, value), el("div", { class: "label" }, label))
    )
  );
}

function renderPreview() {
  const { rooms, devices } = state.result;
  const svg = $("preview");
  svg.replaceChildren();

  // Legend
  $("legend").replaceChildren(
    ...Object.keys(TYPE_COLORS).map((type) =>
      el("span", {}, el("i", { class: "dot", style: `background:${TYPE_COLORS[type]}` }), TYPE_LABELS[type])
    ),
    el("span", {}, el("i", { class: "dot", style: "background:#9ca3af" }), "Outside any room")
  );

  // Bounds of everything we draw
  const points = [];
  rooms.forEach((r) => r.coords.forEach((p) => points.push(p)));
  devices.forEach((d) => points.push([d.x, d.y]));
  if (!points.length) return;

  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const scale = 1000 / Math.max(maxX - minX, maxY - minY, 1);
  const width = (maxX - minX) * scale;
  const height = (maxY - minY) * scale;

  // Convert drawing coordinates to SVG coordinates (flip Y axis)
  const tx = (x) => (x - minX) * scale;
  const ty = (y) => (maxY - y) * scale;

  svg.setAttribute("viewBox", `-20 -20 ${width + 40} ${height + 40}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

  const zones = [...new Set(rooms.map((r) => r.zone))].sort();
  const zoneHue = (zone) => (zones.indexOf(zone) * 67) % 360;

  // Larger rooms first so small rooms stay clickable on top
  [...rooms]
    .sort((a, b) => b.area_m2 - a.area_m2)
    .forEach((room) => {
      const hue = zoneHue(room.zone);
      const polygon = svgEl("polygon", {
        points: room.coords.map((p) => `${tx(p[0])},${ty(p[1])}`).join(" "),
        fill: `hsl(${hue} 70% 55%)`,
        "fill-opacity": "0.25",
        stroke: `hsl(${hue} 60% 35%)`,
        "stroke-width": "1.5",
      });
      polygon.addEventListener("click", () => focusRoom(room.id));
      const title = svgEl("title");
      title.textContent = `${room.name} (${room.room_type}, ${room.area_m2} m2)`;
      polygon.append(title);
      svg.append(polygon);
    });

  // Room labels
  rooms.forEach((room) => {
    const cx = room.coords.reduce((a, p) => a + tx(p[0]), 0) / room.coords.length;
    const cy = room.coords.reduce((a, p) => a + ty(p[1]), 0) / room.coords.length;
    const label = svgEl("text", {
      x: cx,
      y: cy,
      "text-anchor": "middle",
      "font-size": "12",
      fill: "#374151",
      "pointer-events": "none",
    });
    label.textContent = room.name;
    svg.append(label);
  });

  // Devices
  devices.forEach((d) => {
    const dot = svgEl("circle", {
      cx: tx(d.x),
      cy: ty(d.y),
      r: 4,
      fill: d.room_id ? TYPE_COLORS[d.device_type] || "#111827" : "#9ca3af",
      stroke: "#fff",
      "stroke-width": "1",
    });
    const title = svgEl("title");
    title.textContent = `${d.id}: ${d.device_type} (${d.block_name})`;
    dot.append(title);
    svg.append(dot);
  });
}

function renderRooms() {
  const { rooms, estimates } = state.result;
  const container = $("rooms");
  container.replaceChildren();

  container.append(el("h3", { class: "zone-title" }, "Whole house"));
  container.append(wholeHouseCard(rooms, estimates));

  const byZone = new Map();
  rooms.forEach((room) => {
    if (!byZone.has(room.zone)) byZone.set(room.zone, []);
    byZone.get(room.zone).push(room);
  });

  [...byZone.keys()].sort().forEach((zone) => {
    container.append(el("h3", { class: "zone-title" }, zone));
    byZone.get(zone).forEach((room) => container.append(roomCard(room, estimates)));
  });
}

function roomCard(room, estimates) {
  const rows = estimates.filter((e) => e.room_id === room.id);
  const roomTotal = rows.reduce((acc, e) => acc + e.total, 0);

  const nameInput = el("input", {
    type: "text",
    value: room.name,
    onchange: (ev) => sendUpdate({ room_id: room.id, name: ev.target.value }),
  });
  const zoneInput = el("input", {
    type: "text",
    value: room.zone,
    onchange: (ev) => sendUpdate({ room_id: room.id, zone: ev.target.value }),
  });
  const typeSelect = el(
    "select",
    { onchange: (ev) => sendUpdate({ room_id: room.id, room_type: ev.target.value }) },
    state.room_types.map((type) => el("option", { value: type, selected: type === room.room_type }, type))
  );

  const head = el(
    "div",
    { class: "room-head" },
    el("label", {}, "Name", nameInput),
    el("label", {}, "Room type", typeSelect),
    el("label", {}, "Zone", zoneInput),
    el(
      "div",
      { class: "meta" },
      `${room.id} | ${room.area_m2} m2 | room confidence ${Math.round(room.confidence * 100)}%`,
      el("br"),
      `Total devices: ${roomTotal}`
    )
  );

  const table = el(
    "table",
    {},
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        el("th", {}, "Device"),
        el("th", { class: "num" }, "Detected"),
        el("th", { class: "num" }, "Estimated"),
        el("th", { class: "num" }, "Recommended"),
        el("th", { class: "num" }, "Total"),
        el("th", { class: "num" }, "Confidence"),
        el("th", {}, "Verified"),
        el("th", {}, "Reason")
      )
    ),
    el(
      "tbody",
      {},
      rows.map((e) => estimateRow(room, e))
    )
  );

  return el("div", { class: "room-card", id: `room-${room.id}` }, head, table);
}

function wholeHouseCard(rooms, estimates) {
  const roomName = Object.fromEntries(rooms.map((r) => [r.id, r.name]));

  // Sum all rooms by device type, and keep each room's contribution
  const byType = {};
  estimates.forEach((e) => {
    const row = (byType[e.device_type] ||= { total: 0, parts: [] });
    row.total += e.total;
    if (e.total > 0) row.parts.push({ name: roomName[e.room_id], value: e.total });
  });

  // Build "Bedroom 17 + Bathroom 21 = 38"
  const formula = (row) =>
    row.parts.length
      ? `${row.parts.map((p) => `${p.name} ${p.value}`).join(" + ")} = ${row.total}`
      : "0";

  const types = Object.keys(byType);
  const grand = types.reduce((acc, t) => acc + byType[t].total, 0);
  const totalArea = rooms.reduce((acc, r) => acc + r.area_m2, 0).toFixed(1);

  const head = el(
    "div",
    { class: "room-head" },
    el("strong", {}, "Whole house / apartment"),
    el("div", { class: "meta" }, `${rooms.length} rooms | ${totalArea} m2`, el("br"), `Total devices: ${grand}`)
  );

  const table = el(
    "table",
    {},
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        el("th", {}, "Device"),
        el("th", { class: "num" }, "Whole house"),
        el("th", {}, "Calculation (sum of rooms)")
      )
    ),
    el(
      "tbody",
      {},
      types.map((t) =>
        el(
          "tr",
          {},
          el("td", {}, TYPE_LABELS[t] || t),
          el("td", { class: "num" }, el("strong", {}, byType[t].total)),
          el("td", { class: "reason" }, formula(byType[t]))
        )
      ),
      el(
        "tr",
        {},
        el("td", {}, el("strong", {}, "Total")),
        el("td", { class: "num" }, el("strong", {}, grand)),
        el("td", { class: "reason" }, `All device types = ${grand}`)
      )
    )
  );

  return el("div", { class: "room-card whole-house", id: "whole-house" }, head, table);
}

function estimateRow(room, e) {
  const quantityInput = (field) =>
    el("input", {
      type: "number",
      min: "0",
      step: "1",
      value: e[field],
      onchange: (ev) => {
        const value = Math.max(0, parseInt(ev.target.value, 10) || 0);
        sendUpdate({ room_id: room.id, device_type: e.device_type, [field]: value });
      },
    });

  return el(
    "tr",
    { class: e.confidence < LOW_CONFIDENCE ? "low-conf" : "" },
    el("td", {}, TYPE_LABELS[e.device_type] || e.device_type),
    el("td", { class: "num" }, e.detected),
    el("td", { class: "num" }, quantityInput("estimated")),
    el("td", { class: "num" }, quantityInput("recommended")),
    el("td", { class: "num" }, el("strong", {}, e.total)),
    el("td", { class: "num conf" }, `${Math.round(e.confidence * 100)}%`),
    el(
      "td",
      {},
      el("input", {
        type: "checkbox",
        checked: e.verified,
        onchange: (ev) => sendUpdate({ room_id: room.id, device_type: e.device_type, verified: ev.target.checked }),
      })
    ),
    el("td", { class: "reason" }, e.reason)
  );
}

function focusRoom(roomId) {
  const card = $(`room-${roomId}`);
  if (!card) return;
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.add("flash");
  setTimeout(() => card.classList.remove("flash"), 1500);
}

// ---------- Events ----------

$("upload-btn").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", (ev) => {
  const file = ev.target.files[0];
  if (file) uploadFile(file);
});
$("export-btn").addEventListener("click", () => {
  window.location.href = "/export";
});

loadExisting();