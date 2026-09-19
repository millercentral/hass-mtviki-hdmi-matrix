/*
 * MT-ViKI Matrix Card
 * Bundled with the mtviki_hdmi_matrix integration and loaded automatically.
 *
 * type: custom:mtviki-matrix-card
 * device_id: <optional; defaults to the first MT-ViKI matrix>
 * title: <optional; defaults to the device name>
 * show_all: true        # "All outputs" row
 * show_presets: true    # preset recall/save
 */

const PLATFORM = "mtviki_hdmi_matrix";
const CARD_VERSION = "0.1.0";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);

class MtvikiMatrixCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._signature = "";
    this._preset = 1;
    this._pending = new Set();
    this._confirmSave = false;
    this._confirmTimer = null;
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
  }

  static getStubConfig() {
    return {};
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "device_id", selector: { device: { filter: { integration: PLATFORM } } } },
        { name: "title", selector: { text: {} } },
        { name: "show_all", selector: { boolean: {} } },
        { name: "show_presets", selector: { boolean: {} } },
      ],
      computeLabel: (s) =>
        ({
          device_id: "Matrix (leave empty for the first one found)",
          title: "Title (defaults to the device name)",
          show_all: "Show the \"All outputs\" row",
          show_presets: "Show presets",
        })[s.name],
    };
  }

  setConfig(config) {
    this._config = { show_all: true, show_presets: true, ...(config || {}) };
    this._signature = "";
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    const outputs = this._model()?.outputs.length ?? 2;
    return 2 + outputs + (this._config.show_all ? 1 : 0) + (this._config.show_presets ? 1 : 0);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  // ------------------------------------------------------------------ model

  _entries() {
    const hass = this._hass;
    if (!hass) return [];
    if (hass.entities) {
      return Object.values(hass.entities).filter((e) => e.platform === PLATFORM);
    }
    // Fallback for very old frontends: recognise our entities by attributes.
    return Object.keys(hass.states)
      .filter((id) => {
        const a = hass.states[id].attributes;
        return a.output_index !== undefined || a.action !== undefined;
      })
      .map((entity_id) => ({ entity_id, device_id: null }));
  }

  _model() {
    const hass = this._hass;
    if (!hass) return null;
    let entries = this._entries();
    let deviceId = this._config.device_id;
    if (!deviceId) deviceId = entries.find((e) => e.device_id)?.device_id ?? null;
    if (deviceId) entries = entries.filter((e) => e.device_id === deviceId);

    const outputs = [];
    const routeAll = {};
    const recall = {};
    const save = {};
    for (const entry of entries) {
      const st = hass.states[entry.entity_id];
      if (!st) continue;
      const a = st.attributes;
      if (entry.entity_id.startsWith("select.") && a.output_index !== undefined) {
        outputs.push({
          entity_id: entry.entity_id,
          index: a.output_index,
          name: a.output_name || `Output ${a.output_index}`,
          input: a.input_index,
          options: a.options || [],
          state: st.state,
        });
      } else if (entry.entity_id.startsWith("button.")) {
        if (a.action === "route_all") routeAll[a.input_index] = entry.entity_id;
        else if (a.action === "recall") recall[a.preset] = entry.entity_id;
        else if (a.action === "save") save[a.preset] = entry.entity_id;
      }
    }
    outputs.sort((x, y) => x.index - y.index);
    if (!outputs.length) return null;

    const inputs = outputs[0].options.slice(1); // options[0] is "None"
    const device = deviceId && hass.devices ? hass.devices[deviceId] : null;
    const title =
      this._config.title ?? (device ? device.name_by_user || device.name : "HDMI Matrix");
    const available = outputs.every((o) => o.state !== "unavailable");
    const presets = Object.keys(recall).map(Number).sort((a, b) => a - b);
    return { title, outputs, inputs, routeAll, recall, save, presets, available };
  }

  // ----------------------------------------------------------------- render

  _render() {
    const m = this._model();
    const sig = JSON.stringify([
      m, this._config, this._preset, [...this._pending], this._confirmSave,
    ]);
    if (sig === this._signature) return;
    this._signature = sig;

    if (!m) {
      this.shadowRoot.innerHTML = `${STYLE}<ha-card><div class="empty">
        No MT-ViKI HDMI matrix found. Add the integration under
        Settings &rarr; Devices &amp; services.</div></ha-card>`;
      return;
    }

    const cols = m.inputs.length + 1;
    const dis = m.available ? "" : "disabled";
    const cell = (active, attrs, label, extra = "") =>
      `<button class="cell ${active ? "active" : ""} ${extra}" ${attrs} ${dis}
        title="${esc(label)}" aria-pressed="${active}" aria-label="${esc(label)}">
        ${active ? '<ha-icon icon="mdi:check"></ha-icon>' : ""}</button>`;

    let grid = `<div class="corner"></div>`;
    m.inputs.forEach((name) => (grid += `<div class="colhead">${esc(name)}</div>`));
    grid += `<div class="colhead">Off</div>`;

    for (const o of m.outputs) {
      grid += `<div class="rowhead">${esc(o.name)}</div>`;
      m.inputs.forEach((name, i) => {
        const key = `${o.entity_id}|${i + 1}`;
        grid += cell(
          o.input === i + 1,
          `data-select="${esc(o.entity_id)}" data-option="${esc(name)}" data-key="${esc(key)}"`,
          `${o.name}: ${name}`,
          this._pending.has(key) ? "pending" : "",
        );
      });
      const offKey = `${o.entity_id}|0`;
      grid += cell(
        o.input === 0,
        `data-select="${esc(o.entity_id)}" data-option="${esc(o.options[0] || "None")}" data-key="${esc(offKey)}"`,
        `${o.name}: off`,
        `off ${this._pending.has(offKey) ? "pending" : ""}`,
      );
    }

    if (this._config.show_all && Object.keys(m.routeAll).length) {
      grid += `<div class="sep"></div><div class="rowhead all">All outputs</div>`;
      const allSame = (n) => m.outputs.every((o) => o.input === n);
      [...m.inputs.map((_, i) => i + 1), 0].forEach((n) => {
        const id = m.routeAll[n];
        const label = n ? `All outputs: ${m.inputs[n - 1]}` : "All outputs: off";
        grid += id
          ? cell(allSame(n), `data-press="${esc(id)}" data-key="${esc(id)}"`, label,
              `${n ? "" : "off"} ${this._pending.has(id) ? "pending" : ""}`)
          : "<div></div>";
      });
    }

    let presets = "";
    if (this._config.show_presets && m.presets.length) {
      const opts = m.presets
        .map((p) => `<option value="${p}" ${p === this._preset ? "selected" : ""}>Preset ${p}</option>`)
        .join("");
      presets = `<div class="presets">
        <select class="preset" aria-label="Preset" ${dis}>${opts}</select>
        <button class="action" data-preset-action="recall" ${dis}>
          <ha-icon icon="mdi:playlist-play"></ha-icon>Recall</button>
        <button class="action ${this._confirmSave ? "confirm" : ""}" data-preset-action="save" ${dis}>
          <ha-icon icon="mdi:content-save"></ha-icon>${this._confirmSave ? "Confirm save" : "Save"}</button>
      </div>`;
    }

    this.shadowRoot.innerHTML = `${STYLE}<ha-card>
      <div class="header">
        <div class="title">${esc(m.title)}</div>
        ${m.available ? "" : '<div class="status">Offline</div>'}
      </div>
      <div class="grid" style="--cols:${cols}">${grid}</div>
      ${presets}
    </ha-card>`;
  }

  // ---------------------------------------------------------------- actions

  _onChange(ev) {
    const sel = ev.target.closest("select.preset");
    if (sel) {
      this._preset = Number(sel.value);
      this._confirmSave = false;
    }
  }

  _onClick(ev) {
    const btn = ev.target.closest("button");
    if (!btn || btn.disabled || !this._hass) return;

    if (btn.dataset.select) {
      this._call(btn.dataset.key, "select", "select_option", {
        entity_id: btn.dataset.select,
        option: btn.dataset.option,
      });
    } else if (btn.dataset.press) {
      this._call(btn.dataset.key, "button", "press", { entity_id: btn.dataset.press });
    } else if (btn.dataset.presetAction) {
      const m = this._model();
      if (!m) return;
      if (btn.dataset.presetAction === "recall") {
        const id = m.recall[this._preset];
        if (id) this._call(id, "button", "press", { entity_id: id });
      } else if (!this._confirmSave) {
        // Saving overwrites the stored preset, so ask for a second click.
        this._confirmSave = true;
        clearTimeout(this._confirmTimer);
        this._confirmTimer = setTimeout(() => {
          this._confirmSave = false;
          this._render();
        }, 4000);
        this._render();
      } else {
        this._confirmSave = false;
        clearTimeout(this._confirmTimer);
        const id = m.save[this._preset];
        if (id) {
          this._call(id, "button", "press", { entity_id: id }).then((ok) => {
            if (ok) this._toast(`Saved current routing to preset ${this._preset}`);
          });
        }
      }
    }
  }

  async _call(key, domain, service, data) {
    this._pending.add(key);
    this._render();
    try {
      await this._hass.callService(domain, service, data);
      return true;
    } catch (err) {
      this._toast(err?.message || "The HDMI matrix did not respond");
      return false;
    } finally {
      this._pending.delete(key);
      this._render();
    }
  }

  _toast(message) {
    this.dispatchEvent(
      new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }),
    );
  }
}

const STYLE = `<style>
  ha-card { padding: 16px; }
  .header { display: flex; align-items: center; justify-content: space-between;
    gap: 8px; margin-bottom: 12px; }
  .title { font-size: 1.2em; font-weight: 500; line-height: 1.3; }
  .status { font-size: 0.75em; padding: 2px 10px; border-radius: 10px;
    background: var(--error-color, #db4437); color: var(--text-primary-color, #fff); }
  .empty { color: var(--secondary-text-color); }
  .grid { display: grid; gap: 6px; align-items: center;
    grid-template-columns: fit-content(34%) repeat(var(--cols), minmax(0, 1fr)); }
  .colhead { font-size: 0.75em; color: var(--secondary-text-color); text-align: center;
    line-height: 1.2; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2;
    -webkit-box-orient: vertical; overflow-wrap: break-word; hyphens: auto; }
  .rowhead { font-weight: 500; font-size: 0.9em; overflow-wrap: anywhere; padding-right: 4px; }
  .rowhead.all { font-weight: 400; color: var(--secondary-text-color); }
  .sep { grid-column: 1 / -1; height: 1px; background: var(--divider-color); margin: 4px 0; }
  button { font: inherit; cursor: pointer; }
  button:disabled { opacity: 0.45; cursor: default; }
  .cell { min-height: 40px; border-radius: 10px; padding: 0;
    border: 1px solid var(--divider-color, #ccc);
    background: var(--secondary-background-color, transparent);
    color: var(--primary-text-color); display: flex; align-items: center;
    justify-content: center; transition: background 0.15s, border-color 0.15s; }
  .cell:not(:disabled):hover { border-color: var(--primary-color); }
  .cell.active { background: var(--primary-color); border-color: var(--primary-color);
    color: var(--text-primary-color, #fff); }
  .cell.off.active { background: var(--secondary-text-color);
    border-color: var(--secondary-text-color); }
  .cell.pending { opacity: 0.55; }
  .cell ha-icon { --mdc-icon-size: 20px; }
  .cell:focus-visible, .action:focus-visible, select:focus-visible {
    outline: 2px solid var(--primary-color); outline-offset: 2px; }
  .presets { display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
    margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--divider-color); }
  select.preset { flex: 1 1 110px; min-height: 36px; border-radius: 8px; padding: 0 8px;
    border: 1px solid var(--divider-color); background: var(--card-background-color);
    color: var(--primary-text-color); font: inherit; }
  .action { display: inline-flex; align-items: center; gap: 6px; min-height: 36px;
    padding: 0 14px; border-radius: 18px; border: 1px solid var(--primary-color);
    background: transparent; color: var(--primary-color); }
  .action ha-icon { --mdc-icon-size: 18px; }
  .action.confirm { background: var(--warning-color, #ffa600);
    border-color: var(--warning-color, #ffa600); color: var(--text-primary-color, #fff); }
</style>`;

if (!customElements.get("mtviki-matrix-card")) {
  customElements.define("mtviki-matrix-card", MtvikiMatrixCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "mtviki-matrix-card",
    name: "MT-ViKI Matrix Card",
    description: "Route HDMI inputs to outputs and recall presets on an MT-ViKI matrix.",
    preview: true,
    documentationURL: "https://github.com/millercentral/hass-mtviki-hdmi-matrix",
  });
  console.info(`%c MTVIKI-MATRIX-CARD %c ${CARD_VERSION} `,
    "background:#03a9f4;color:#fff", "background:#444;color:#fff");
}
