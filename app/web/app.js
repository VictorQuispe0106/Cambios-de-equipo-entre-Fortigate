// ============================================================
// SPIDER-SENSE · Suit Lab Backup
// Spider-Man × Tony Stark · MCU Theme
// ============================================================

const state = {
  inputText: "",
  templateText: "",
  outputText: "",
  filename: "spider_sense_backup.conf",
  detectedModel: null,
  layout: null,
  mapping: {},
  log: [],
  warnings: [],
  balanceIssues: [],
  renameCounts: {},
  claroInjected: false,
  reassignments: [],
  wouldBeDiscarded: [],
  availableLanSlots: [],
  switchInterfaces: [],
  validation: null,
  dryRunResult: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ============================================================
// EASTER EGGS
// ============================================================

const PETER_QUIPS = [
  '"With great power comes great network backups."',
  '"Spider-Sense me dice que este backup está correcto."',
  '"JARVIS, hazme un backup. Pero no le digas a Tony."',
  '"Un gran poder requiere un gran config system interface."',
  '"No way. No way. No way we are doing this."',
  '"Esto es lo que pasa cuando Spider-Man hace DevOps."',
  '"Mi sentido arácnido me dice que el puerto 80F es el correcto."',
  '"Tony me dio el traje. Yo le doy backups."',
  '"Si esto falla, culpa de Tony. Si funciona, mío."',
  '"El Spider-Sense no falla. Y yo tampoco."',
];

function getRandomQuip() {
  return PETER_QUIPS[Math.floor(Math.random() * PETER_QUIPS.length)];
}

// Konami code listener
const konamiSequence = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight', 'b', 'a'];
let konamiIndex = 0;

document.addEventListener('keydown', (e) => {
  const key = e.key.toLowerCase();
  const expected = konamiSequence[konamiIndex].toLowerCase();
  if (key === expected) {
    konamiIndex++;
    if (konamiIndex === konamiSequence.length) {
      activateEndgameMode();
      konamiIndex = 0;
    }
  } else {
    konamiIndex = 0;
  }
});

function activateEndgameMode() {
  document.body.classList.toggle('endgame-mode');
  const isActive = document.body.classList.contains('endgame-mode');
  setStatus(isActive
    ? "⚡ ENDGAME MODE · nanobots amplificados · Stark Industries aprueba"
    : "✓ Endgame mode desactivado", isActive ? "ok" : "");
}

// Logo quip on click
$("#mainLogo").addEventListener("click", () => {
  const sub = $("#brandSubtitle");
  sub.textContent = getRandomQuip();
  sub.style.color = "var(--spider-red-soft)";
  sub.style.fontWeight = "700";
setTimeout(() => {
      sub.textContent = "Suit Lab · backup del traje arañudo · powered by Stark Industries";
      sub.style.color = "";
      sub.style.fontWeight = "";
    }, 3500);
});

// ============================================================
// HELPERS
// ============================================================

function setStatus(text, level = "") {
  const el = $("#status");
  el.className = "status " + level;
  el.innerHTML = `<span class="status-text">${escapeHtml(text)}</span>`;
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function updateProcessButton() {
  const canProcess = !!state.inputText && !!state.templateText;
  $("#btnProcess").disabled = !canProcess;
  $("#btnDryRun").disabled = !canProcess;
  if (canProcess) {
    $("#btnProcess").classList.add("ready");
    $("#btnDryRun").classList.add("ready");
  }
}

function updateHudStats() {
  const slots = (state.layout?.slots || []).map(s => s.toLowerCase());
  const wan = slots.filter(s => s.startsWith("wan")).length;
  const special = new Set(["dmz", "mgmt", "ha1", "ha2", "modem"]);
  const port = slots.filter(s => !s.startsWith("wan") && !special.has(s)).length;
  const rename = Object.keys(state.mapping).length;
  const reassign = state.reassignments.filter(r => r.target_slot).length;
  $("#statWan").textContent = wan;
  $("#statPort").textContent = port;
  $("#statRename").textContent = rename;
  $("#statReassign").textContent = reassign;

  // Mostrar telarana animada cuando hay archivos
  const hudStats = $("#hudStats");
  if (state.inputText && state.templateText) {
    hudStats.classList.add("has-data");
  } else {
    hudStats.classList.remove("has-data");
  }
}

// Typewriter effect para JARVIS
function typewriter(element, text, speed = 22) {
  element.textContent = "";
  element.classList.add("typing");
  const dot = document.querySelector(".jarvis-pulse");
  const status = document.querySelector(".jarvis-status");
  if (status) status.classList.add("jarvis-speaking");
  if (dot) dot.style.background = "var(--stark-cyan-soft)";

  let i = 0;
  const tick = () => {
    if (i < text.length) {
      element.textContent += text.charAt(i);
      i++;
      setTimeout(tick, speed);
    } else {
      element.classList.remove("typing");
      if (status) status.classList.remove("jarvis-speaking");
      if (dot) dot.style.background = "";
    }
  };
  tick();
}

function simpleDiff(a, b) {
  const A = a.split(/\r?\n/);
  const B = b.split(/\r?\n/);
  const max = Math.max(A.length, B.length);
  const out = [];
  for (let i = 0; i < max; i++) {
    const la = A[i];
    const lb = B[i];
    if (la === undefined && lb !== undefined) {
      out.push(`<span class="added">+ ${escapeHtml(lb)}</span>`);
    } else if (lb === undefined && la !== undefined) {
      out.push(`<span class="removed">- ${escapeHtml(la)}</span>`);
    } else if (la !== lb) {
      if (la !== undefined) out.push(`<span class="removed">- ${escapeHtml(la)}</span>`);
      if (lb !== undefined) out.push(`<span class="added">+ ${escapeHtml(lb)}</span>`);
    } else {
      out.push(`<span class="ctx">  ${escapeHtml(la ?? "")}</span>`);
    }
  }
  return out.join("\n");
}

// Syntax highlighting para output
function highlightConf(text) {
  const escaped = escapeHtml(text);
  return escaped
    .replace(/^(\s*)(config\s+\S+)/gm, '$1<span style="color: var(--stark-cyan-soft); font-weight: 600">$2</span>')
    .replace(/^(\s*)(edit\s+"[^"]+")/gm, '$1<span style="color: var(--honeycomb-gold); font-weight: 600">$2</span>')
    .replace(/^(\s*)(end|next)/gm, '$1<span style="color: var(--venom-purple); font-weight: 600">$2</span>')
    .replace(/^(\s*)(set\s+)(\S+)/gm, '$1$2<span style="color: var(--arc-reactor)">$3</span>')
    .replace(/^(\s*)(#.*)$/gm, '$1<span style="color: var(--muted); font-style: italic">$2</span>');
}

// ============================================================
// FILE LOADING
// ============================================================

$("#fileInput").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const text = await f.text();
  state.inputText = text;
  state.filename = f.name.replace(/\.conf$/i, "") + "_mark_lxxxv.conf";
  $("#fileMeta").textContent = `${f.name} - ${text.length.toLocaleString()} bytes · escaneado por JARVIS`;
  $("#fileLabel").textContent = f.name;
  $("label[for='fileInput']").classList.add("has-file");
  setStatus(`✓ Mark actual cargado: ${f.name} · JARVIS firmando el traje`, "ok");
  updateProcessButton();
  updateHudStats();
  if (state.templateText) await refreshPreview();
});

$("#templateInput").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  await loadTemplateText(await f.text(), f.name);
});

async function loadTemplateText(text, label) {
  state.templateText = text;
  $("#templateLabel").textContent = label;
  $("#templateMeta").textContent = `${label} · ${text.length.toLocaleString()} bytes`;
  $("label[for='templateInput']").classList.add("has-file");

  const previewEl = $("#templatePreview");
  previewEl.classList.remove("empty", "detected", "error");
  previewEl.classList.add("detected");
  previewEl.innerHTML = `
    <div class="jarvis-header">
      <span class="jarvis-pulse"></span>
      <span class="jarvis-label">JARVIS:</span>
      <span class="jarvis-text" id="jarvisStatus"></span>
    </div>
  `;

  try {
    const statusEl = previewEl.querySelector("#jarvisStatus");
    typewriter(statusEl, "Stark Industries: escaneando arquitectura del nuevo Mark...");

    const r = await fetch("/api/preview-template", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template: text, text: state.inputText || "" }),
    });
    const j = await r.json();
    if (!j.ok && j.error) {
      throw new Error(j.error);
    }
    state.layout = {
      model_hint: j.model_hint,
      slots: j.slots || [],
      lan_count: j.lan_count,
      wan_count: j.wan_count,
      has_mgmt: j.has_mgmt,
      has_dmz: j.has_dmz,
      has_ha: j.has_ha,
    };
    state.availableLanSlots = j.lan_names || [];
    state.switchInterfaces = j.switch_interfaces || [];

    statusEl.textContent = "Analisis completo · Mark compatible con tu traje";
    setTimeout(() => renderTemplatePreview(j), 700);

    const excedentes = j.excedentes || j.reassignments || [];
    const discarded = j.would_be_discarded_if_no_manual || j.would_be_discarded || [];
    setTimeout(() => renderReassignments(excedentes, discarded, j.slots || []), 700);
    setStatus(excedentes && excedentes.length
      ? `⚠ ${excedentes.length} modulo(s) del Mark actual no existen en el destino · elige donde reubicarlos o dejalos vacios para descartar`
      : "✓ JARVIS listo · traje destino compatible con tu Mark actual", "ok");
    updateHudStats();
  } catch (e) {
    previewEl.classList.remove("detected");
    previewEl.classList.add("error");
    previewEl.innerHTML = `
    <div class="jarvis-header"><span class="jarvis-pulse" style="background: var(--danger)"></span><span class="jarvis-label" style="color: var(--danger)">STARK INDUSTRIES:</span><span class="jarvis-text">${escapeHtml(e.message || String(e))}</span></div>`;
    setStatus("✖ Conexión con JARVIS interrumpida: " + (e.message || e), "error");
    state.templateText = "";
    $("label[for='templateInput']").classList.remove("has-file");
  }
  updateProcessButton();
}

async function refreshPreview() {
  if (!state.templateText) return;
  try {
    const r = await fetch("/api/preview-template", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template: state.templateText, text: state.inputText }),
    });
    const j = await r.json();
    if (!j.ok) return;
    const excedentes = j.excedentes || j.reassignments || [];
    const discarded = j.would_be_discarded_if_no_manual || j.would_be_discarded || [];
    renderReassignments(excedentes, discarded, j.slots || []);
    updateHudStats();
  } catch (e) {
    console.error("preview refresh failed", e);
  }
}

function renderTemplatePreview(layout) {
  const previewEl = $("#templatePreview");
  previewEl.classList.remove("empty", "error");
  previewEl.classList.add("detected");

  const modelLabel = layout.model_hint || "modelo destino";
  const flags = [];
  if (layout.has_mgmt) flags.push("mgmt");
  if (layout.has_dmz) flags.push("dmz");
  if (layout.has_ha) flags.push("HA");
  const flagStr = flags.length ? ` · ${flags.join(" · ")}` : "";

  const slotsHtml = (layout.slots || [])
    .map((s) => {
      const sl = s.toLowerCase();
      const isSpecial = ["dmz", "mgmt", "ha1", "ha2"].includes(sl) || sl.startsWith("wan");
      return `<span class="slot-chip${isSpecial ? " special" : ""}">${escapeHtml(s)}</span>`;
    })
    .join("");

  previewEl.innerHTML = `
    <div class="template-preview-head">
      <span class="badge">${escapeHtml(modelLabel)}</span>
      <span class="template-summary">${escapeHtml(layout.summary || `${layout.lan_count} puertos LAN${flagStr}`)}</span>
    </div>
    <div class="template-slots">${slotsHtml}</div>
  `;
}

function renderReassignments(excedentes, discarded, allSlots) {
  const section = $("#reassignSection");
  const list = $("#reassignList");
  const disc = $("#reassignDiscarded");
  const discList = $("#reassignDiscardedList");
  const countEl = $("#reassignCount");

  state.reassignments = excedentes;

  if (!excedentes || excedentes.length === 0) {
    section.classList.add("hidden");
    list.innerHTML = "";
    disc.classList.add("hidden");
    updateHudStats();
    return;
  }

  section.classList.remove("hidden");
  countEl.textContent = `${excedentes.length} módulos`;

  const nativeOccupied = (state.layout && state.layout.slots) || [];
  // Destinos de reasignacion: slots fisicos + switches de hardware del
  // destino (ej. LAN2_CLIENTE). El usuario decide donde reubicar.
  const switchNames = (state.switchInterfaces || []).map(s => s.name)
    .filter(n => !(allSlots || []).includes(n));
  const options = (allSlots || []).concat(switchNames);

  const rows = excedentes.map((r, idx) => {
    const selectedSlot = r.target_slot || "";
    const opts = [`<option value="" disabled ${selectedSlot === "" ? "selected" : ""}>— elegir slot destino —</option>`]
      .concat(options.map((s) => {
        const selected = s === selectedSlot ? "selected" : "";
        const label = switchNames.includes(s) ? `${s} (switch)` : s;
        return `<option value="${escapeHtml(s)}" ${selected}>${escapeHtml(label)}</option>`;
      }))
      .join("");
    const hasAuto = selectedSlot !== "";
    return `
      <div class="reassign-row ${hasAuto ? "" : "needs-attention"}" data-idx="${idx}">
        <span class="src-name">${escapeHtml(r.src_name)}</span>
        <span class="src-kind">${escapeHtml(r.src_kind)}</span>
        <span class="arrow">→</span>
        <select class="reassign-select" data-idx="${idx}">${opts}</select>
        <span class="reassign-hint" data-idx="${idx}"></span>
      </div>
    `;
  }).join("");
  list.innerHTML = rows;

  const update = () => {
    const selects = document.querySelectorAll(".reassign-select");
    const targets = Array.from(selects).map(s => s.value).filter(v => v !== "");
    const hasDup = new Set(targets).size !== targets.length;

    selects.forEach((sel) => {
      const v = sel.value;
      const idx = parseInt(sel.dataset.idx, 10);
      const row = sel.closest(".reassign-row");
      const hint = row.querySelector(".reassign-hint");

      sel.classList.remove("duplicate", "overwriting-native", "empty");

      if (v === "") {
        sel.classList.add("empty");
        row.classList.add("needs-attention");
        hint.textContent = "⚠ sin asignar (se descartará)";
        hint.className = "reassign-hint warn";
      } else if (nativeOccupied.includes(v) && v === excedentes[idx].target_slot) {
        hint.textContent = "";
        hint.className = "reassign-hint";
      } else if (nativeOccupied.includes(v)) {
        sel.classList.add("overwriting-native");
        row.classList.remove("needs-attention");
        hint.textContent = "⚠ desplazará al slot nativo";
        hint.className = "reassign-hint warn";
      } else {
        hint.textContent = "✓ slot libre";
        hint.className = "reassign-hint ok";
        row.classList.remove("needs-attention");
      }

      if (hasDup && targets.filter(t => t === v).length > 1) {
        sel.classList.add("duplicate");
      }
    });
  };
  update();

  document.querySelectorAll(".reassign-select").forEach((sel) => {
    sel.addEventListener("change", (e) => {
      const idx = parseInt(e.target.dataset.idx, 10);
      state.reassignments[idx].target_slot = e.target.value;
      update();
      updateHudStats();
    });
  });

  if (discarded && discarded.length > 0) {
    disc.classList.remove("hidden");
    discList.textContent = `Si dejas dropdowns vacíos, se descartarán: ${discarded.join(", ")}`;
  } else {
    disc.classList.add("hidden");
  }
  updateHudStats();
}

// ============================================================
// TABS
// ============================================================

$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.remove("active"));
    $$(".tab-body").forEach((b) => b.classList.remove("active"));
    tab.classList.add("active");
    document.querySelector(`.tab-body[data-tab="${tab.dataset.tab}"]`).classList.add("active");
  });
});

// ============================================================
// COPY OUTPUT
// ============================================================

$("#btnCopyOutput").addEventListener("click", async () => {
  if (!state.outputText) {
    setStatus("✖ No hay output que copiar.", "warn");
    return;
  }
  try {
    await navigator.clipboard.writeText(state.outputText);
    const btn = $("#btnCopyOutput");
    btn.classList.add("copied");
    btn.textContent = "✓ Copiado";
    setTimeout(() => {
      btn.classList.remove("copied");
      btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
    }, 1500);
  } catch (e) {
    setStatus("✖ Error al copiar al portapapeles.", "error");
  }
});

// ============================================================
// DRY-RUN — Simulacion sin generar output
// ============================================================

$("#btnDryRun").addEventListener("click", async () => {
    if (!state.inputText) {
      setStatus("✖ Falta el traje actual.", "warn");
      return;
    }
    if (!state.templateText) {
      setStatus("✖ Falta el traje destino.", "warn");
      return;
    }

    const profile = {
      text: state.inputText,
      template: state.templateText,
      inject_admin: $("#injectAdmin").checked,
      reassignments: state.reassignments && state.reassignments.length > 0
        ? state.reassignments.map(r => ({
            src_name: r.src_name,
            src_kind: r.src_kind,
            target_slot: r.target_slot,
            original_role: r.original_role,
          }))
        : undefined,
    };

    const btn = $("#btnDryRun");
    const btnText = btn.querySelector(".btn-text");
    const originalText = btnText.textContent;
    btn.disabled = true;
    btnText.textContent = "Simulando...";

    try {
      const r = await fetch("/api/dry-run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      const j = await r.json();
      if (!j.ok) {
        setStatus("✖ Simulación falló: " + (j.error || "desconocido"), "error");
        btnText.textContent = originalText;
        btn.disabled = false;
        updateProcessButton();
        return;
      }

      state.dryRunResult = j;
      state.validation = j.validation;

      renderDryRunResults(j);
      const validLabel = j.validation?.is_valid ? "✓" : "⚠";
      setStatus(`${validLabel} Simulación completa · ${j.diff_stats?.lines_changed || 0} líneas cambiarán · ${j.unrenamed_refs_count || 0} refs sin renombrar · ${j.orphaned_refs_count || 0} refs huérfanas`, j.validation?.is_valid ? "ok" : "warn");
    } catch (e) {
      setStatus("✖ Error en simulación: " + e.message, "error");
    }

    btnText.textContent = originalText;
    btn.disabled = false;
    updateProcessButton();
});

function renderDryRunResults(j) {
  const container = $("#dryRunResults") || createDryRunPanel();

  let html = `<div class="dry-run-header">`;
  html += `<span class="badge ${j.validation?.is_valid ? 'badge-ok' : 'badge-warn'}">${j.validation?.is_valid ? '✓ VALIDO' : '⚠ CON PROBLEMAS'}</span>`;
  html += `<span class="dry-run-summary">${escapeHtml(j.detected_model || '?')} → ${escapeHtml(j.target_model_hint || '?')} · ${j.diff_stats?.lines_changed || 0} líneas cambiarán</span>`;
  html += `</div>`;

  if (j.validation) {
    html += `<div class="dry-run-section">`;
    html += `<h4>Estadísticas del output</h4>`;
    html += `<div class="dry-run-stats">`;
    html += `<span>Configs: ${j.validation.stats?.config_count || 0}</span>`;
    html += `<span>Edits: ${j.validation.stats?.edit_count || 0}</span>`;
    html += `<span>Sets: ${j.validation.stats?.set_count || 0}</span>`;
    html += `<span>Líneas: ${j.validation.stats?.line_count || 0}</span>`;
    html += `</div>`;
    html += `</div>`;

    if (j.validation.errors?.length > 0) {
      html += `<div class="dry-run-section dry-run-errors">`;
      html += `<h4>Errores (${j.validation.errors.length})</h4>`;
      html += j.validation.errors.map(e => `<div class="dry-run-error">✖ ${escapeHtml(e)}</div>`).join('');
      html += `</div>`;
    }

    if (j.validation.warnings?.length > 0) {
      html += `<div class="dry-run-section dry-run-warnings">`;
      html += `<h4>Warnings (${j.validation.warnings.length})</h4>`;
      html += j.validation.warnings.map(w => `<div class="dry-run-warn">⚠ ${escapeHtml(w)}</div>`).join('');
      html += `</div>`;
    }
  }

  if (j.unrenamed_refs_count > 0 || j.orphaned_refs_count > 0) {
    html += `<div class="dry-run-section dry-run-refs">`;
    html += `<h4>Referencias problemáticas</h4>`;
    if (j.unrenamed_refs_count > 0) {
      html += `<div class="dry-run-warn">⚠ ${j.unrenamed_refs_count} referencia(s) a interfaces no renombradas</div>`;
    }
    if (j.orphaned_refs_count > 0) {
      html += `<div class="dry-run-error">✖ ${j.orphaned_refs_count} referencia(s) a interfaces no definidas</div>`;
    }
    html += `</div>`;
  }

  container.innerHTML = html;
  container.classList.remove("hidden");
}

function createDryRunPanel() {
  const panel = document.createElement("section");
  panel.id = "dryRunResults";
  panel.className = "card dry-run-card";
  const actionsBar = $(".actions-bar");
  actionsBar.parentNode.insertBefore(panel, actionsBar.nextSibling);
  return panel;
}

// ============================================================
// PROCESS — 3 fases + glitch
// ============================================================

$("#btnProcess").addEventListener("click", async () => {
    if (!state.inputText) {
      setStatus("✖ Falta el traje actual.", "warn");
      return;
    }
    if (!state.templateText) {
      setStatus("✖ Falta el traje destino.", "warn");
      return;
    }

    const profile = {
      text: state.inputText,
      template: state.templateText,
      inject_admin: $("#injectAdmin").checked,
      reassignments: state.reassignments && state.reassignments.length > 0
        ? state.reassignments.map(r => ({
            src_name: r.src_name,
            src_kind: r.src_kind,
            target_slot: r.target_slot,
            original_role: r.original_role,
          }))
        : undefined,
    };

    const btn = $("#btnProcess");
    const btnText = btn.querySelector(".btn-text");
    const originalText = btnText.textContent;
    btn.disabled = true;
    btn.classList.add("processing");

    // FASE 1: Conectando nanobots
    btnText.textContent = "Conectando nanobots";
    setStatus("⚡ Inicializando nanobots · conectando al Mark LXXXV...", "");
    await sleep(400);

    // FASE 2: Reconfigurando modulos
    btnText.textContent = "Reconfigurando modulos";
    setStatus("🔧 Tony esta reconfigurando el Mark · Spider-Man aguarda...", "");
    await sleep(500);

    // GLITCH effect
    document.body.classList.add("glitch-mode");
    setTimeout(() => document.body.classList.remove("glitch-mode"), 200);

    try {
      const r = await fetch("/api/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      const j = await r.json();
      if (!j.ok) {
        setStatus("✖ Despliegue falló: " + (j.error || "desconocido"), "error");
        btnText.textContent = originalText;
        btn.classList.remove("processing");
        btn.disabled = false;
        updateProcessButton();
        return;
      }

      state.detectedModel = j.detected_model;
      state.layout = { model_hint: j.target_model_hint, slots: j.target_slots || [] };
      state.switchInterfaces = j.target_switch_interfaces || [];
      state.mapping = j.mapping;
      state.log = j.log;
      state.warnings = j.warnings;
      state.outputText = j.output_text;
      state.balanceIssues = j.balance_issues;
      state.renameCounts = j.rename_counts;
      state.claroInjected = j.claro_injected;

      renderMapping();
      renderWarnings();
      renderDiff();
      renderOutput();

      const hasIssues = (j.warnings && j.warnings.length) || (j.balance_issues && j.balance_issues.length);
      const raCount = j.reassignments ? j.reassignments.length : 0;

      // FASE 3: Traje desplegado
      btnText.textContent = "✓ Mark listo";
      const warningSummary = j.warnings && j.warnings.length > 0
        ? ` · ⚠ ${j.warnings.length} interface(s) descartada(s) sin slot`
        : "";
      setStatus(`🕷️ Traje desplegado · ${j.detected_model || "?"} → ${j.target_model_hint || "(?)"} · ${Object.keys(j.mapping).length} interfaces optimizadas · ${raCount} reasignadas · claro: ${j.claro_injected ? "instalado" : "no"}${warningSummary}`, hasIssues ? "warn" : "ok");
      $("#btnDownload").disabled = false;
      updateHudStats();

      // Random Peter quip on success
      if (!hasIssues) {
        setTimeout(() => {
          const fq = $("#footerQuote");
          if (fq) fq.textContent = getRandomQuip();
        }, 1500);
      }

      // Restore button
      setTimeout(() => {
        btnText.textContent = originalText;
        btn.classList.remove("processing");
        btn.disabled = false;
        updateProcessButton();
      }, 2000);
    } catch (e) {
      setStatus("✖ Conexión con JARVIS interrumpida: " + e.message, "error");
      btnText.textContent = originalText;
      btn.classList.remove("processing");
      btn.disabled = false;
      updateProcessButton();
    }
});

function sleep(ms) {
  return new Promise(res => setTimeout(res, ms));
}

// ============================================================
// RENDERING
// ============================================================

function renderMapping() {
  const keys = Object.keys(state.mapping);
  const lines = [];
  lines.push(`<span class="section-title">Renombrado físico (${keys.length})</span>`);
  if (!keys.length) {
    lines.push(`<span class="ctx map-line">  Sin cambios.</span>`);
  } else {
    for (const k of keys) {
      lines.push(
        `<span class="map-line">  <code>${escapeHtml(k)}</code><span class="map-arrow">→</span><code>${escapeHtml(state.mapping[k])}</code></span>`
      );
    }
  }

  if (state.layout && state.layout.slots && state.layout.slots.length) {
    lines.push(`<span class="section-title">Slots del destino (${state.layout.slots.length})</span>`);
    const slotsHtml = state.layout.slots
      .map((s) => `<span class="slot-chip${["dmz", "mgmt", "ha1", "ha2"].includes(s.toLowerCase()) || s.toLowerCase().startsWith("wan") ? " special" : ""}">${escapeHtml(s)}</span>`)
      .join(" ");
    lines.push(`<span class="map-line">${slotsHtml}</span>`);
  }

  lines.push(`<span class="section-title">Log del despliegue</span>`);
  if (!state.log.length) {
    lines.push(`<span class="ctx map-line">  (vacío)</span>`);
  } else {
    for (const l of state.log) {
      lines.push(`<span class="ctx map-line">  ${escapeHtml(l)}</span>`);
    }
  }
  $("#mappingLog").innerHTML = lines.join("\n");
}

function renderWarnings() {
  const w = [...state.warnings, ...state.balanceIssues];
  if (!w.length) {
    $("#warningsLog").innerHTML = '<span class="ctx">Sin alertas de JARVIS.</span>';
    return;
  }
  $("#warningsLog").innerHTML = w.map((m) => '<span class="warn">⚠ ' + escapeHtml(m) + "</span>").join("\n");
}

function renderDiff() {
  if (!state.outputText) {
    $("#diffLog").innerHTML = '<span class="ctx">Sin datos.</span>';
    return;
  }
  $("#diffLog").innerHTML = simpleDiff(state.inputText, state.outputText);
}

function renderOutput() {
  $("#outputLog").innerHTML = state.outputText
    ? highlightConf(state.outputText).slice(0, 120000)
    : '<span class="ctx">Sin datos.</span>';
}

// ============================================================
// DOWNLOAD
// ============================================================

$("#btnDownload").addEventListener("click", async () => {
  if (!state.outputText) {
    setStatus("✖ Nada para descargar. Procesa primero.", "warn");
    return;
  }
  const r = await fetch("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: state.outputText, filename: state.filename }),
  });
  if (!r.ok) {
    setStatus("✖ Error al generar la descarga.", "error");
    return;
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = state.filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
});

// ============================================================
// CREDENCIALES — admin de respaldo (token ENC nunca se muestra)
// ============================================================

function renderCredStatus(creds) {
  const el = $("#credStatus");
  el.textContent = `Credenciales: usuario ${creds.user} · ${creds.token_configured ? "token configurado" : "no configurado"}`;
  el.classList.toggle("configured", !!creds.token_configured);
}

async function loadCredentials() {
  try {
    const r = await fetch("/api/credentials");
    const j = await r.json();
    if (!j.ok) return;
    renderCredStatus(j);
    // El token NUNCA viaja en la respuesta: el input queda vacio siempre.
    if (!$("#credUser").value) $("#credUser").value = j.user || "claro";
  } catch (e) {
    console.error("credenciales no disponibles", e);
    $("#credStatus").textContent = "Credenciales: no disponibles";
  }
}

$("#btnSaveCreds").addEventListener("click", async () => {
  const user = $("#credUser").value.trim();
  const encToken = $("#credToken").value.trim();
  if (!user || !encToken) {
    setStatus("✖ Credenciales incompletas: indica usuario y token ENC.", "warn");
    return;
  }
  const btn = $("#btnSaveCreds");
  const btnText = btn.querySelector(".btn-text");
  const originalText = btnText.textContent;
  btn.disabled = true;
  btnText.textContent = "Guardando...";
  try {
    const r = await fetch("/api/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user, enc_token: encToken }),
    });
    const j = await r.json();
    if (!r.ok || !j.ok) {
      setStatus("✖ Credenciales rechazadas: " + (j.error || "error desconocido"), "error");
      return;
    }
    // Exito: el token nunca se rellena en el input; se limpia y se
    // refleja solo el estado via status line.
    $("#credToken").value = "";
    renderCredStatus(j);
    setStatus(`✓ Credenciales guardadas · usuario ${j.user} · token configurado`, "ok");
  } catch (e) {
    setStatus("✖ Error guardando credenciales: " + e.message, "error");
  } finally {
    btnText.textContent = originalText;
    btn.disabled = false;
  }
});

loadCredentials();

// ============================================================
// GLITCH CSS via class
// ============================================================

const style = document.createElement("style");
style.textContent = `
  body.glitch-mode::before {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 9999;
    background: linear-gradient(transparent 48%, rgba(0, 212, 255, 0.15) 50%, transparent 52%);
    animation: scan-glitch 0.2s ease-in-out;
  }
  @keyframes scan-glitch {
    0%, 100% { transform: translateX(0); }
    33% { transform: translateX(-4px); }
    66% { transform: translateX(4px); }
  }
`;
document.head.appendChild(style);