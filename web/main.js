let state = null;
let maxDevices = 12;

const elPorts = document.getElementById("ports");
const elStatus = document.getElementById("status");
const elGrid = document.getElementById("grid");
const tpl = document.getElementById("cardTpl");

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function setStatus(connected) {
  elStatus.textContent = connected ? "ONLINE" : "OFFLINE";
  elStatus.style.borderColor = connected ? "rgba(47,227,140,.55)" : "rgba(255,91,110,.55)";
  elStatus.style.color = connected ? "rgba(47,227,140,.95)" : "rgba(255,91,110,.95)";
}

async function refreshPorts() {
  const ports = await window.pywebview.api.list_ports();
  elPorts.innerHTML = "";
  for (const p of ports) {
    const opt = document.createElement("option");
    opt.value = p;
    opt.textContent = p;
    elPorts.appendChild(opt);
  }
}

function fmtVal(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number" && Number.isFinite(v)) return v.toFixed(3);
  return String(v);
}

function renderCards() {
  elGrid.innerHTML = "";
  for (let i = 0; i < maxDevices; i++) {
    const d = state.devices[i];
    const node = tpl.content.cloneNode(true);

    const card = node.querySelector(".card");
    node.querySelector(".idx").textContent = String(i + 1);

    const btnToggle = node.querySelector(".toggle");
    btnToggle.textContent = d.active ? "ON" : "OFF";
    btnToggle.classList.toggle("primary", d.active);
    btnToggle.classList.toggle("danger", !d.active);

    const inpTag = node.querySelector(".tag");
    inpTag.value = d.tag;

    const btnSaveTag = node.querySelector(".saveTag");

    const inpCons = node.querySelector(".consigne");
    inpCons.value = d.consigne ?? 0;

    const btnCons = node.querySelector(".applyConsigne");

    const elMesure = node.querySelector(".mesure");
    elMesure.textContent = `${d.mesure.unit} ${fmtVal(Number(d.mesure.value))}`;

    const elTotal = node.querySelector(".total");
    elTotal.textContent = `${d.total.unit} ${fmtVal(Number(d.total.value))}`;

    const elVanne = node.querySelector(".vanne");
    elVanne.textContent = d.valve;

    const selVanne = node.querySelector(".vanneCmd");
    selVanne.value = "Régulation";
    const btnVanne = node.querySelector(".applyVanne");

    const chkRamp = node.querySelector(".rampActive");
    const inpRampTime = node.querySelector(".rampTime");
    const btnRamp = node.querySelector(".applyRamp");
    chkRamp.checked = !!d.ramp.active;
    inpRampTime.value = d.ramp.time_s ?? 1.0;

    const selGas = node.querySelector(".gas");
    selGas.innerHTML = "";
    for (const g of (d.gases || [])) {
      const opt = document.createElement("option");
      opt.value = g;
      opt.textContent = g;
      selGas.appendChild(opt);
    }

    // events
    btnToggle.addEventListener("click", async () => {
      try {
        state = await window.pywebview.api.toggle_device(i, !d.active);
        setStatus(state.connected);
        renderCards();
      } catch (e) {
        alert("Erreur toggle: " + e);
      }
    });

    btnSaveTag.addEventListener("click", async () => {
      await window.pywebview.api.set_tag(i, inpTag.value);
      // pas besoin de snapshot, mais on refresh local
      state.devices[i].tag = inpTag.value.slice(0, 8).padEnd(8, "_");
      renderCards();
    });

    btnCons.addEventListener("click", async () => {
      try {
        const val = Number(inpCons.value);
        state = await window.pywebview.api.set_consigne(i, val);
        renderCards();
      } catch (e) {
        alert("Erreur consigne: " + e);
      }
    });

    btnVanne.addEventListener("click", async () => {
      try {
        state = await window.pywebview.api.set_vanne(i, selVanne.value);
        renderCards();
      } catch (e) {
        alert("Erreur vanne: " + e);
      }
    });

    btnRamp.addEventListener("click", async () => {
      try {
        state = await window.pywebview.api.set_ramp(i, chkRamp.checked, Number(inpRampTime.value));
        renderCards();
      } catch (e) {
        alert("Erreur rampe: " + e);
      }
    });

    node.querySelector(".resetTotal").addEventListener("click", async () => {
      try {
        state = await window.pywebview.api.reset_total(i);
        renderCards();
      } catch (e) {
        alert("Erreur RAZ total: " + e);
      }
    });

    selGas.addEventListener("change", async () => {
      try {
        state = await window.pywebview.api.select_gas(i, selGas.value);
        renderCards();
      } catch (e) {
        alert("Erreur sélection gaz: " + e);
      }
    });

    elGrid.appendChild(node);
  }
}

async function boot() {
  const info = await window.pywebview.api.get_app_info();
  if (info.settings?.theme === "light") {
    document.body.classList.add("light");
  }
  document.getElementById("version").textContent = `${info.name} • ${info.version}`;
  maxDevices = info.max || 12;

  await refreshPorts();

  // init snapshot
  state = await window.pywebview.api.snapshot();
  setStatus(state.connected);
  renderCards();

  // polling UI (on re-tire un snapshot régulièrement)
  while (true) {
    try {
      state = await window.pywebview.api.snapshot();
      setStatus(state.connected);
      renderCards();
    } catch (_e) { }
    await sleep(800);
  }
}

document.getElementById("refreshPorts").addEventListener("click", refreshPorts);

document.getElementById("connect").addEventListener("click", async () => {
  const port = elPorts.value;
  if (!port) return;
  try {
    state = await window.pywebview.api.connect(port);
    setStatus(state.connected);
    renderCards();
  } catch (e) {
    alert("Erreur connect: " + e);
  }
});

document.getElementById("disconnect").addEventListener("click", async () => {
  state = await window.pywebview.api.disconnect();
  setStatus(state.connected);
  renderCards();
});

document.getElementById("theme").addEventListener("click", async () => {
  // ultra simple: toggle light/dark côté front
  document.body.classList.toggle("light");
  await window.pywebview.api.set_theme(document.body.classList.contains("light") ? "light" : "dark");
});

window.addEventListener("pywebviewready", boot);
