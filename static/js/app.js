// TASHIL DOCUMENT HUB — Web Edition — app.js
// Vanilla JS, no build step required (runs identically via Termux + browser).

// Safe replacement for `await res.json()` used throughout this file. The
// backend now always returns JSON on /api/ routes (see app.py's global
// error handlers), but this is a defense-in-depth backstop against any
// non-JSON response reaching the frontend (e.g. from something outside
// Flask entirely, like a captive-portal page on a public Wi-Fi). Without
// this, a non-JSON body throws a cryptic "Unexpected token '<'..." error
// instead of a readable message.
async function parseJsonResponse(res) {
  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    const text = await res.text();
    throw new Error(
      `Réponse inattendue du serveur (HTTP ${res.status})` +
      (text ? ` : ${text.slice(0, 150)}` : "")
    );
  }
  return res.json();
}

const state = {
  profile: null,
  meta: null,
  session: null,
  currentView: "dashboard",
  lastKnownReceived: null,
  notifyPermissionAsked: false,
  pendingUnlockKey: null,   // institution_key currently shown on the PIN screen
  pendingUnlockNeedsSetup: false,
  appInitialized: false,    // event listeners wired only once (see showApp)
  selectedFile: null,       // currently attached file in the Envoi form
  bridgeEnabled: false,
};

// ------------------------------------------------------------------ //
// Boot
// ------------------------------------------------------------------ //
async function boot() {
  const theme = localStorage.getItem("tashil_theme") || "dark";
  document.documentElement.setAttribute("data-theme", theme);

  const [metaRes, sessionRes] = await Promise.all([
    fetch("/api/meta").then(r => r.json()),
    fetch("/api/session").then(r => r.json()),
  ]);
  state.meta = metaRes;
  state.session = sessionRes;

  if (sessionRes.first_launch) {
    showOnboarding({ allowCancel: false });
  } else if (sessionRes.active) {
    state.profile = sessionRes.active;
    showApp();
  } else {
    showLockScreen();
  }
}

// ------------------------------------------------------------------ //
// Onboarding (creating a NEW institution profile)
// ------------------------------------------------------------------ //
function showOnboarding({ allowCancel }) {
  document.getElementById("lock-overlay").classList.add("hidden");
  document.getElementById("onboarding-overlay").classList.remove("hidden");

  const wilayaSelect = document.getElementById("ob-wilaya");
  wilayaSelect.innerHTML = "";
  state.meta.wilayas.forEach(([code, name]) => {
    const opt = document.createElement("option");
    opt.value = code;
    opt.textContent = `${String(code).padStart(2, "0")} - ${name}`;
    if (code === 31) opt.selected = true; // default Oran
    wilayaSelect.appendChild(opt);
  });

  const typeSelect = document.getElementById("ob-type");
  typeSelect.innerHTML = "";
  state.meta.institution_types.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    typeSelect.appendChild(opt);
  });

  wilayaSelect.addEventListener("change", refreshOnboardingInstitutions);
  typeSelect.addEventListener("change", refreshOnboardingInstitutions);
  refreshOnboardingInstitutions();

  document.getElementById("ob-submit").onclick = submitOnboarding;

  const cancelBtn = document.getElementById("ob-cancel");
  if (allowCancel) {
    cancelBtn.classList.remove("hidden");
    cancelBtn.onclick = () => {
      document.getElementById("onboarding-overlay").classList.add("hidden");
      showLockScreen();
    };
  } else {
    cancelBtn.classList.add("hidden");
  }
}

async function refreshOnboardingInstitutions() {
  const wilayaCode = parseInt(document.getElementById("ob-wilaya").value, 10);
  const institutionType = document.getElementById("ob-type").value;
  const nameSelect = document.getElementById("ob-name-select");
  const nameManual = document.getElementById("ob-name-manual");

  nameSelect.innerHTML = `<option value="">Chargement...</option>`;
  try {
    const data = await fetch(
      `/api/institutions/onboarding?wilaya_code=${wilayaCode}&institution_type=${encodeURIComponent(institutionType)}`
    ).then(r => r.json());

    nameSelect.innerHTML = "";
    (data.institutions || []).forEach(name => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      nameSelect.appendChild(opt);
    });
    const otherOpt = document.createElement("option");
    otherOpt.value = "__other__";
    otherOpt.textContent = "Autre (saisir manuellement)";
    nameSelect.appendChild(otherOpt);

    nameSelect.onchange = () => {
      const manual = nameSelect.value === "__other__";
      nameManual.classList.toggle("hidden", !manual);
      if (manual) nameManual.focus();
    };
    nameManual.classList.add("hidden");
  } catch (err) {
    nameSelect.innerHTML = `<option value="__other__">Autre (saisir manuellement)</option>`;
    nameManual.classList.remove("hidden");
  }
}

async function submitOnboarding() {
  const errorEl = document.getElementById("ob-error");
  errorEl.classList.add("hidden");

  const nameSelect = document.getElementById("ob-name-select");
  const nameManual = document.getElementById("ob-name-manual");
  const institutionName = nameSelect.value === "__other__"
    ? nameManual.value.trim()
    : nameSelect.value;

  const pin = document.getElementById("ob-pin").value.trim();
  const pinConfirm = document.getElementById("ob-pin-confirm").value.trim();

  if (!institutionName) {
    errorEl.textContent = "Veuillez indiquer le nom de l'établissement.";
    errorEl.classList.remove("hidden");
    return;
  }
  if (!/^\d{4,6}$/.test(pin)) {
    errorEl.textContent = "Le code PIN doit contenir 4 à 6 chiffres.";
    errorEl.classList.remove("hidden");
    return;
  }
  if (pin !== pinConfirm) {
    errorEl.textContent = "Les deux codes PIN ne correspondent pas.";
    errorEl.classList.remove("hidden");
    return;
  }

  const payload = {
    wilaya_code: parseInt(document.getElementById("ob-wilaya").value, 10),
    institution_type: document.getElementById("ob-type").value,
    institution_name: institutionName,
    pin,
  };

  try {
    const res = await fetch("/api/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Erreur inconnue.");

    state.profile = data.profile;
    document.getElementById("onboarding-overlay").classList.add("hidden");
    showApp();
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove("hidden");
  }
}

// ------------------------------------------------------------------ //
// Lock screen — profile picker + PIN entry
// ------------------------------------------------------------------ //
async function showLockScreen() {
  document.getElementById("app").classList.add("hidden");
  document.getElementById("onboarding-overlay").classList.add("hidden");
  document.getElementById("lock-overlay").classList.remove("hidden");
  document.getElementById("lock-pin-step").classList.add("hidden");
  // Explicitly reset to defaults every time — a previous call may have
  // left these hidden mid-PIN-entry (selectProfileForUnlock hides them).
  // Without this reset, a fresh call from a different entry point (e.g.
  // after deleting a profile) could land on a stuck, mostly-blank screen.
  document.getElementById("lock-profile-list").classList.remove("hidden");
  document.getElementById("lock-add-profile-btn").classList.remove("hidden");

  try {
    const session = await fetch("/api/session").then(r => r.json());
    state.session = session;
    renderProfileList(session.profiles);
    document.getElementById("lock-add-profile-btn").onclick = () => {
      document.getElementById("lock-overlay").classList.add("hidden");
      showOnboarding({ allowCancel: session.profiles.length > 0 });
    };
  } catch (err) {
    // Never leave the screen stuck blank with no way forward — this is
    // exactly the failure mode that previously showed as a frozen gray
    // screen with just the static "TASHIL DOCUMENT HUB" title visible.
    document.getElementById("lock-profile-list").innerHTML = `
      <p class="empty-state">
        ⛔ Impossible de charger la liste des établissements.<br>
        <button class="btn btn-secondary" id="lock-retry-btn" style="margin-top:10px;">🔄 Réessayer</button>
      </p>`;
    document.getElementById("lock-retry-btn").addEventListener("click", showLockScreen);
  }
}

function renderProfileList(profiles) {
  const container = document.getElementById("lock-profile-list");
  if (!profiles.length) {
    container.innerHTML = "";
    return;
  }
  container.innerHTML = profiles.map(p => `
    <div class="profile-item" data-key="${escapeHtml(p.institution_key)}">
      <div>
        <div class="profile-item-name">${escapeHtml(p.institution_name)}</div>
        <div class="profile-item-sub">${escapeHtml(p.wilaya_name)} — ${escapeHtml(p.institution_type)}</div>
      </div>
      <span class="profile-item-badge">${p.pin_set ? "🔒" : "⚙️ à configurer"}</span>
    </div>
  `).join("");

  container.querySelectorAll(".profile-item").forEach(el => {
    el.addEventListener("click", () => selectProfileForUnlock(el.dataset.key, profiles));
  });
}

function selectProfileForUnlock(key, profiles) {
  const profile = profiles.find(p => p.institution_key === key);
  state.pendingUnlockKey = key;
  state.pendingUnlockNeedsSetup = !profile.pin_set;

  document.getElementById("lock-profile-list").classList.add("hidden");
  document.getElementById("lock-add-profile-btn").classList.add("hidden");
  const pinStep = document.getElementById("lock-pin-step");
  pinStep.classList.remove("hidden");

  const pinInput = document.getElementById("lock-pin-input");
  const pinConfirmInput = document.getElementById("lock-pin-confirm-input");
  pinInput.value = "";
  pinConfirmInput.value = "";
  document.getElementById("lock-error").classList.add("hidden");

  if (state.pendingUnlockNeedsSetup) {
    document.getElementById("lock-pin-label").textContent =
      `Créez un code PIN pour ${profile.institution_name}`;
    pinConfirmInput.classList.remove("hidden");
    document.getElementById("lock-unlock-btn").textContent = "✅ Définir le code PIN";
  } else {
    document.getElementById("lock-pin-label").textContent =
      `Code PIN — ${profile.institution_name}`;
    pinConfirmInput.classList.add("hidden");
    document.getElementById("lock-unlock-btn").textContent = "🔓 Déverrouiller";
  }
  pinInput.focus();

  document.getElementById("lock-unlock-btn").onclick = submitUnlock;
  document.getElementById("lock-back-btn").onclick = () => {
    pinStep.classList.add("hidden");
    document.getElementById("lock-profile-list").classList.remove("hidden");
    document.getElementById("lock-add-profile-btn").classList.remove("hidden");
  };
}

async function submitUnlock() {
  const errorEl = document.getElementById("lock-error");
  errorEl.classList.add("hidden");

  const pin = document.getElementById("lock-pin-input").value.trim();
  if (!/^\d{4,6}$/.test(pin)) {
    errorEl.textContent = "Le code PIN doit contenir 4 à 6 chiffres.";
    errorEl.classList.remove("hidden");
    return;
  }

  try {
    let res, data;
    if (state.pendingUnlockNeedsSetup) {
      const pinConfirm = document.getElementById("lock-pin-confirm-input").value.trim();
      if (pin !== pinConfirm) {
        errorEl.textContent = "Les deux codes PIN ne correspondent pas.";
        errorEl.classList.remove("hidden");
        return;
      }
      res = await fetch("/api/session/set-pin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ institution_key: state.pendingUnlockKey, pin }),
      });
    } else {
      res = await fetch("/api/session/unlock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ institution_key: state.pendingUnlockKey, pin }),
      });
    }
    data = await res.json();
    if (!res.ok) throw new Error(data.error || "Échec du déverrouillage.");

    state.profile = data.profile;
    document.getElementById("lock-overlay").classList.add("hidden");
    showApp();
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove("hidden");
  }
}

// ------------------------------------------------------------------ //
// App shell
// ------------------------------------------------------------------ //
function showApp() {
  document.getElementById("lock-overlay").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  document.getElementById("institution-name").textContent =
    state.profile ? state.profile.institution_name : "—";

  // One-time event wiring only — re-running this on every unlock would
  // stack duplicate listeners (double sends, double toasts) and spawn
  // multiple concurrent polling intervals, since locking no longer
  // reloads the page.
  if (!state.appInitialized) {
    setupNav();
    setupThemeToggle();
    setupMessaging();
    setupUpdateChecker();
    setupLogout();
    setupDeleteProfile();
    setupLockButton();
    setupRefreshButton();
    setupCopyLanUrl();
    setupCloudBridge();
    startBackgroundPolling();
    state.appInitialized = true;
  }

  // Per-unlock refresh: must never carry over from a previously active
  // profile (this is the actual data-isolation guarantee on the frontend
  // side — the backend already isolates storage, this ensures the UI
  // doesn't show stale counts from the last institution either).
  state.lastKnownReceived = null;
  resetMessagingForm();
  renderParametres();
  loadDashboard();
  loadInstitutions();
  requestNotificationPermission();
  switchView("dashboard");

  document.getElementById("lan-url").textContent = state.meta.lan_url;
  document.getElementById("network-qr-img").src = `/api/network-qr.png?t=${Date.now()}`;
  document.getElementById("current-version").textContent = `v${state.meta.app_version}`;
}

function setupLockButton() {
  document.getElementById("lock-btn").onclick = lockSession;
}

function setupRefreshButton() {
  document.getElementById("refresh-btn").onclick = manualRefresh;
}

async function manualRefresh() {
  const btn = document.getElementById("refresh-btn");
  btn.classList.add("spinning");
  try {
    // Always poll the bridge (cheap no-op if not configured — pollBridge
    // checks state.bridgeEnabled itself) so a manual refresh reliably
    // surfaces anything new without waiting for the 45s background timer.
    await pollBridge(false);

    if (state.currentView === "dashboard") await loadDashboard();
    else if (state.currentView === "messagerie") {
      await loadInbox();
      await loadDashboard(); // keeps stat cards current even off-screen
    } else if (state.currentView === "registre") {
      const activeFilter = document.querySelector(".subtab[data-filter].active");
      await loadRegistre(activeFilter ? activeFilter.dataset.filter : "tous");
    } else if (state.currentView === "etablissements") {
      await loadEtablissements();
    } else if (state.currentView === "parametres") {
      await refreshBridgeUI();
    }
    showToast("🔄 Actualisé", "success");
  } catch (err) {
    showToast("⛔ Échec de l'actualisation", "error");
  } finally {
    btn.classList.remove("spinning");
  }
}

function setupCopyLanUrl() {
  document.getElementById("copy-lan-url-btn").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(state.meta.lan_url);
      showToast("📋 Lien copié", "success");
    } catch (err) {
      // Clipboard API can be unavailable in some webview contexts —
      // the URL is already shown as plain text as a fallback.
      showToast("⛔ Impossible de copier automatiquement — copiez le lien affiché.", "error");
    }
  });
}

async function lockSession() {
  try {
    await fetch("/api/session/lock", { method: "POST" });
  } catch (err) {
    // Even if the request fails, still send the user to the lock screen —
    // never leave archives visible on an uncertain network error.
  }
  state.profile = null;
  document.getElementById("app").classList.add("hidden");
  await showLockScreen();
}

// ------------------------------------------------------------------ //
// Toast notifications
// ------------------------------------------------------------------ //
function showToast(message, kind = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${kind}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4500);
}

function requestNotificationPermission() {
  if (state.notifyPermissionAsked) return;
  state.notifyPermissionAsked = true;
  try {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }
  } catch (err) {
    // Notification API unsupported in this environment — toasts still work
  }
}

function showSystemNotification(title, body) {
  try {
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(title, { body, icon: "/static/assets/logo.png" });
    }
  } catch (err) {
    // Silently ignore — the in-app toast already covers this
  }
}

// Generates a short two-tone chime with the Web Audio API — no external
// audio file needed (nothing to bundle/package, works identically on
// every platform). Browsers require a prior user interaction before
// AudioContext can play sound (autoplay policy) — by the time a
// background poll fires the user has normally already clicked something,
// but the very first notification after launch could be silently blocked
// by that policy; this is a known, unavoidable browser constraint, not a
// bug — the toast/visual notification still fires regardless.
function playNotificationSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const now = ctx.currentTime;
    [880, 1320].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0, now + i * 0.12);
      gain.gain.linearRampToValueAtTime(0.2, now + i * 0.12 + 0.02);
      gain.gain.linearRampToValueAtTime(0, now + i * 0.12 + 0.18);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now + i * 0.12);
      osc.stop(now + i * 0.12 + 0.2);
    });
  } catch (err) {
    // Web Audio unsupported in this context — toast/notification still fire
  }
}

// ------------------------------------------------------------------ //
// Background polling — surfaces new received messages as notifications
// without requiring the user to be on the Messagerie tab.
// ------------------------------------------------------------------ //
function startBackgroundPolling() {
  setInterval(async () => {
    try {
      const data = await fetch("/api/dashboard").then(r => r.json());
      if (state.lastKnownReceived === null) {
        state.lastKnownReceived = data.total_received;
      } else if (data.total_received > state.lastKnownReceived) {
        const diff = data.total_received - state.lastKnownReceived;
        state.lastKnownReceived = data.total_received;
        showToast(`📥 ${diff} nouveau(x) message(s) reçu(s)`, "success");
        showSystemNotification("TASHIL DOCUMENT HUB", `${diff} nouveau(x) message(s) reçu(s)`);
        playNotificationSound();
        if (state.currentView === "dashboard") loadDashboard();
        if (state.currentView === "messagerie") loadInbox();
      }
      if (state.currentView === "dashboard") {
        document.getElementById("stat-sent").textContent = data.total_sent;
        document.getElementById("stat-received").textContent = data.total_received;
        document.getElementById("stat-pending").textContent = data.pending;
      }
    } catch (err) {
      // Silent — this is a background convenience poll, not a critical path
    }
  }, 8000);

  // Separate, slower interval for the Cloud Bridge — GitHub API calls,
  // spaced further apart than the local dashboard poll to stay well
  // within rate limits. Only does anything once bridge is configured.
  setInterval(() => pollBridge(false), 45000);
}

async function loadInstitutions() {
  try {
    const data = await fetch("/api/institutions").then(r => r.json());
    const datalist = document.getElementById("institutions-list");
    datalist.innerHTML = data.institutions.map(name =>
      `<option value="${escapeHtml(name)}"></option>`).join("");
  } catch (err) {
    // Datalist is a progressive enhancement — free typing still works if this fails
  }
}

function setupNav() {
  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
  });
}

function switchView(viewName) {
  state.currentView = viewName;
  document.querySelectorAll(".tab").forEach(t =>
    t.classList.toggle("active", t.dataset.view === viewName));
  document.querySelectorAll(".view").forEach(v =>
    v.classList.toggle("active", v.id === `view-${viewName}`));

  if (viewName === "dashboard") loadDashboard();
  if (viewName === "messagerie") loadInbox();
  if (viewName === "registre") loadRegistre("tous");
  if (viewName === "etablissements") loadEtablissements();
}

async function loadEtablissements() {
  const container = document.getElementById("etablissements-list");
  const offCard = document.getElementById("etablissements-bridge-off");

  try {
    const data = await fetch("/api/bridge/directory").then(r => parseJsonResponse(r));
    if (!data.bridge_enabled) {
      offCard.classList.remove("hidden");
      container.innerHTML = "";
      return;
    }
    offCard.classList.add("hidden");

    if (!data.institutions.length) {
      container.innerHTML = `<p class="empty-state">Aucun établissement détecté pour le moment. ` +
        `Ils apparaîtront ici après leur première synchronisation avec le Réseau TASHIL.</p>`;
      return;
    }

    container.innerHTML = data.institutions.map(inst => `
      <div class="list-row">
        <div class="list-row-main">
          <span class="list-row-title">
            <span class="bridge-dot ${inst.online ? "bridge-dot-on" : "bridge-dot-off"}"></span>
            ${escapeHtml(inst.institution_name)}
          </span>
          <span class="list-row-sub">${escapeHtml(inst.wilaya_name)} — ${escapeHtml(inst.institution_type)}</span>
        </div>
        <span class="list-row-badge">${inst.online ? "En ligne" : "Vu " + timeAgo(inst.last_seen)}</span>
      </div>
    `).join("");
  } catch (err) {
    container.innerHTML = `<p class="empty-state">⛔ Impossible de charger la liste des établissements.</p>`;
  }
}

function timeAgo(isoString) {
  const diffMs = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "à l'instant";
  if (mins < 60) return `il y a ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `il y a ${Math.floor(hours / 24)} j`;
}

function setupThemeToggle() {
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("tashil_theme", next);
    fetch("/api/profile/theme", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: next }),
    }).catch(() => {});
  });
}

// ------------------------------------------------------------------ //
// Dashboard
// ------------------------------------------------------------------ //
async function loadDashboard() {
  const data = await fetch("/api/dashboard").then(r => r.json());
  document.getElementById("stat-sent").textContent = data.total_sent;
  document.getElementById("stat-received").textContent = data.total_received;
  document.getElementById("stat-pending").textContent = data.pending;
  if (state.lastKnownReceived === null) state.lastKnownReceived = data.total_received;

  const container = document.getElementById("recent-activity");
  if (!data.recent.length) {
    container.innerHTML = `<p class="empty-state">Aucune activité pour le moment.</p>`;
    return;
  }
  container.innerHTML = data.recent.map(row => `
    <div class="list-row">
      <div class="list-row-main">
        <span class="list-row-title">${row.direction === "sortant" ? "📤" : "📥"} ${escapeHtml(row.tracking_number)}</span>
        <span class="list-row-sub">${escapeHtml(row.subject || "(sans objet)")}</span>
      </div>
      <span class="list-row-badge">${escapeHtml(row.status)}</span>
      <div class="list-row-actions">
        ${row.file_path ? `<button class="row-btn" data-download="${row.id}" title="Télécharger">📥</button>` : ""}
        <button class="row-btn danger" data-delete="${row.id}" data-scope="dashboard" title="Supprimer">🗑️</button>
      </div>
    </div>
  `).join("");
  wireRowActions(container, loadDashboard);
}

// ------------------------------------------------------------------ //
// Shared row actions — download, delete, accusé de réception
// ------------------------------------------------------------------ //
function wireRowActions(container, onChanged) {
  container.querySelectorAll("[data-download]").forEach(btn => {
    btn.addEventListener("click", () => {
      window.open(`/api/messages/${btn.dataset.download}/download`, "_blank");
    });
  });

  container.querySelectorAll("[data-delete]").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("Supprimer définitivement ce document et son archive ?")) return;
      try {
        const res = await fetch(`/api/messages/${btn.dataset.delete}`, { method: "DELETE" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Échec de la suppression.");
        showToast("🗑️ Document supprimé", "success");
        if (onChanged) onChanged();
      } catch (err) {
        showToast(`⛔ ${err.message}`, "error");
      }
    });
  });

  container.querySelectorAll("[data-ack]").forEach(btn => {
    btn.addEventListener("click", async () => {
      try {
        const res = await fetch(`/api/messages/${btn.dataset.ack}/status`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "accuse" }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Échec de la confirmation.");
        showToast("✅ Réception confirmée", "success");
        if (onChanged) onChanged();
      } catch (err) {
        showToast(`⛔ ${err.message}`, "error");
      }
    });
  });
}

// ------------------------------------------------------------------ //
// Messaging
// ------------------------------------------------------------------ //
function resetMessagingForm() {
  state.selectedFile = null;
  const fileInput = document.getElementById("file-input");
  if (fileInput) fileInput.value = "";
  const dropText = document.getElementById("drop-zone-text");
  if (dropText) dropText.textContent = "📎 Glissez un fichier ici ou cliquez pour choisir";
  const statusEl = document.getElementById("msg-send-status");
  if (statusEl) { statusEl.textContent = ""; statusEl.className = "status-line"; }
}

function setupMessaging() {
  document.querySelectorAll(".subtab[data-subview]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".subtab[data-subview]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".subview").forEach(v => v.classList.remove("active"));
      document.getElementById(`sub-${btn.dataset.subview}`).classList.add("active");
      if (btn.dataset.subview === "reception") loadInbox();
    });
  });

  document.querySelectorAll(".subtab[data-filter]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".subtab[data-filter]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      loadRegistre(btn.dataset.filter);
    });
  });

  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");

  dropZone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) {
      state.selectedFile = fileInput.files[0];
      document.getElementById("drop-zone-text").textContent = `📎 ${state.selectedFile.name}`;
    }
  });
  dropZone.addEventListener("dragover", e => { e.preventDefault(); dropZone.classList.add("dragover"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone.addEventListener("drop", e => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length) {
      state.selectedFile = e.dataTransfer.files[0];
      document.getElementById("drop-zone-text").textContent = `📎 ${state.selectedFile.name}`;
    }
  });

  document.getElementById("msg-send-btn").addEventListener("click", async () => {
    const statusEl = document.getElementById("msg-send-status");
    statusEl.className = "status-line";
    statusEl.textContent = "";

    const recipient = document.getElementById("msg-recipient").value.trim();
    if (!state.selectedFile) {
      statusEl.textContent = "Veuillez sélectionner un fichier.";
      statusEl.classList.add("err");
      return;
    }
    if (!recipient) {
      statusEl.textContent = "Veuillez indiquer l'institution destinataire.";
      statusEl.classList.add("err");
      return;
    }

    const formData = new FormData();
    formData.append("file", state.selectedFile);
    formData.append("recipient", recipient);
    formData.append("subject", document.getElementById("msg-subject").value.trim());
    formData.append("body", document.getElementById("msg-body").value.trim());

    try {
      const res = await fetch("/api/messages/send", { method: "POST", body: formData });
      const data = await parseJsonResponse(res);
      if (!res.ok) throw new Error(data.error || "Échec de l'envoi.");

      if (data.delivered_locally) {
        statusEl.textContent = `✅ Document transmis et reçu — ${data.tracking_number}`;
        statusEl.classList.add("ok");
        showToast(`📤 Document remis à ${recipient}`, "success");
        showSystemNotification("TASHIL DOCUMENT HUB", `Document remis à ${recipient}`);
      } else if (data.delivered_via_bridge) {
        // This branch was previously missing entirely — a successful
        // Cloud Bridge delivery was incorrectly reported as "archived,
        // not transmitted" because only delivered_locally was checked.
        statusEl.textContent = `☁️ Document transmis via le Réseau TASHIL — ${data.tracking_number}. ` +
          `En attente de consultation par ${recipient}.`;
        statusEl.classList.add("ok");
        showToast(`☁️ Document transmis via le Cloud Bridge à ${recipient}`, "success");
        showSystemNotification("TASHIL DOCUMENT HUB", `Document transmis à ${recipient} via le Réseau TASHIL`);
      } else if (data.bridge_attempted) {
        statusEl.textContent = `⚠️ Document archivé — ${data.tracking_number}. ` +
          `La transmission via le Réseau TASHIL a échoué (vérifiez la connexion réseau ` +
          `dans Paramètres). Le document reste enregistré ici.`;
        statusEl.classList.add("err");
        showToast(`⚠️ Archivé — échec de la transmission distante`, "error");
      } else {
        statusEl.textContent = `📦 Document archivé — ${data.tracking_number}. ` +
          `Aucun profil "${recipient}" trouvé sur cet appareil, et le Réseau TASHIL n'est ` +
          `pas configuré ici : le document est enregistré mais n'a pas pu être transmis ` +
          `(voir Paramètres → Réseau TASHIL).`;
        statusEl.classList.add("err");
        showToast(`📦 Archivé — non transmis (${recipient} n'a pas de profil ici)`, "info");
      }

      resetMessagingForm();
      document.getElementById("msg-recipient").value = "";
      document.getElementById("msg-subject").value = "";
      document.getElementById("msg-body").value = "";
      loadDashboard();
    } catch (err) {
      statusEl.textContent = `⛔ ${err.message}`;
      statusEl.classList.add("err");
    }
  });
}

async function loadInbox() {
  const data = await fetch("/api/messages?direction=entrant").then(r => r.json());
  const container = document.getElementById("inbox-list");
  if (!data.messages.length) {
    container.innerHTML = `<p class="empty-state">Boîte de réception vide.</p>`;
    return;
  }
  container.innerHTML = data.messages.map(row => `
    <div class="list-row">
      <div class="list-row-main">
        <span class="list-row-title">📥 ${escapeHtml(row.tracking_number)} — ${escapeHtml(row.subject || "(sans objet)")}</span>
        <span class="list-row-sub">De : ${escapeHtml(row.sender_institution || "—")}</span>
      </div>
      <div class="list-row-actions">
        ${row.status === "accuse"
          ? `<span class="list-row-badge">✅ accusé</span>`
          : `<button class="row-btn ack" data-ack="${row.id}" title="Confirmer réception">✅ Accusé</button>`}
        ${row.file_path ? `<button class="row-btn" data-download="${row.id}" title="Télécharger">📥</button>` : ""}
        <button class="row-btn danger" data-delete="${row.id}" title="Supprimer">🗑️</button>
      </div>
    </div>
  `).join("");
  wireRowActions(container, loadInbox);
}

// ------------------------------------------------------------------ //
// Registre
// ------------------------------------------------------------------ //
async function loadRegistre(filter) {
  const data = await fetch(`/api/registre?direction=${filter}`).then(r => r.json());
  const container = document.getElementById("registre-list");
  if (!data.entries.length) {
    container.innerHTML = `<p class="empty-state">Aucun enregistrement.</p>`;
    return;
  }
  container.innerHTML = data.entries.map(row => `
    <div class="list-row">
      <div class="list-row-main">
        <span class="list-row-title">${row.direction === "sortant" ? "📤" : "📥"} ${escapeHtml(row.tracking_number)}</span>
        <span class="list-row-sub">${escapeHtml(row.recipient_institution || row.sender_institution || "—")} — ${escapeHtml(row.subject || "(sans objet)")}</span>
      </div>
      <span class="list-row-badge">${row.created_at.slice(0, 16).replace("T", " ")}</span>
      <div class="list-row-actions">
        ${row.file_path ? `<button class="row-btn" data-download="${row.id}" title="Télécharger">📥</button>` : ""}
        <button class="row-btn danger" data-delete="${row.id}" title="Supprimer">🗑️</button>
      </div>
    </div>
  `).join("");
  wireRowActions(container, () => loadRegistre(filter));
}

// ------------------------------------------------------------------ //
// Paramètres
// ------------------------------------------------------------------ //
function renderParametres() {
  if (!state.profile) return;
  document.getElementById("pf-wilaya").textContent = `Wilaya : ${state.profile.wilaya_name}`;
  document.getElementById("pf-type").textContent = `Type : ${state.profile.institution_type}`;
  document.getElementById("pf-name").textContent = `Nom : ${state.profile.institution_name}`;
  document.getElementById("pf-serial").textContent = state.profile.serial_key;
  document.getElementById("pf-routing-id").textContent = state.profile.institution_key;
}

// ------------------------------------------------------------------ //
// OTA update checker (GitHub Releases API)
// ------------------------------------------------------------------ //
function setupUpdateChecker() {
  document.getElementById("check-update-btn").addEventListener("click", checkForUpdate);
}

function parseVersion(tag) {
  // Accepts "v2.1.0" or "2.1.0"; returns [2,1,0] for comparison
  const clean = tag.replace(/^v/i, "");
  return clean.split(".").map(n => parseInt(n, 10) || 0);
}

function isNewer(remote, current) {
  for (let i = 0; i < Math.max(remote.length, current.length); i++) {
    const r = remote[i] || 0;
    const c = current[i] || 0;
    if (r > c) return true;
    if (r < c) return false;
  }
  return false;
}

async function checkForUpdate() {
  const statusEl = document.getElementById("update-status");
  const banner = document.getElementById("update-banner");
  statusEl.className = "status-line";
  statusEl.textContent = "Recherche en cours...";
  banner.classList.add("hidden");

  try {
    const res = await fetch(
      `https://api.github.com/repos/${state.meta.github_repo}/releases/latest`,
      { headers: { "Accept": "application/vnd.github+json" } }
    );
    if (!res.ok) throw new Error(`GitHub a répondu avec le statut ${res.status}`);
    const release = await res.json();

    const remoteVersion = parseVersion(release.tag_name || "0.0.0");
    const currentVersion = parseVersion(state.meta.app_version);

    if (isNewer(remoteVersion, currentVersion)) {
      const asset = (release.assets || []).find(a => a.name.endsWith(".exe"));
      document.getElementById("update-message").textContent =
        `Nouvelle version disponible : ${release.tag_name} (actuelle : v${state.meta.app_version})`;
      document.getElementById("update-download-link").href =
        asset ? asset.browser_download_url : release.html_url;
      banner.classList.remove("hidden");
      statusEl.textContent = "";
    } else {
      statusEl.textContent = "✅ TASHIL est à jour.";
    }
  } catch (err) {
    statusEl.textContent = `⛔ Impossible de vérifier les mises à jour : ${err.message}`;
  }
}

// ------------------------------------------------------------------ //
// Cloud Bridge (GitHub-backed remote transmission)
// ------------------------------------------------------------------ //
function setupCloudBridge() {
  document.getElementById("bridge-save-btn").addEventListener("click", saveBridgeConfig);
  document.getElementById("bridge-import-btn").addEventListener("click", importBridgeCode);
  document.getElementById("bridge-poll-btn").addEventListener("click", () => pollBridge(true));
  document.getElementById("bridge-disable-btn").addEventListener("click", disableBridge);
  document.getElementById("bridge-show-qr-btn").addEventListener("click", toggleProvisioningQr);
  document.getElementById("network-test-btn").addEventListener("click", runNetworkTest);
  setupQrImageInput();
  refreshBridgeUI();
}

function setupQrImageInput() {
  const dropZone = document.getElementById("qr-drop-zone");
  const fileInput = document.getElementById("qr-file-input");

  dropZone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) decodeQrImageFile(fileInput.files[0]);
  });
  dropZone.addEventListener("dragover", e => { e.preventDefault(); dropZone.classList.add("dragover"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone.addEventListener("drop", e => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length) decodeQrImageFile(e.dataTransfer.files[0]);
  });
}

async function decodeQrImageFile(file) {
  const statusEl = document.getElementById("qr-decode-status");
  statusEl.className = "status-line";
  statusEl.textContent = "Décodage de l'image...";

  const formData = new FormData();
  formData.append("image", file);

  try {
    const res = await fetch("/api/bridge/decode-qr-image", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Échec du décodage.");

    document.getElementById("bridge-import-input").value = data.code;
    statusEl.textContent = "✅ QR décodé — vérifiez puis cliquez sur Importer.";
    statusEl.classList.add("ok");
  } catch (err) {
    statusEl.textContent = `⛔ ${err.message}`;
    statusEl.classList.add("err");
  }
}

async function runNetworkTest() {
  const statusEl = document.getElementById("network-test-status");
  statusEl.className = "status-line";
  statusEl.textContent = "Test en cours...";

  try {
    const res = await fetch("/api/bridge/network-test");
    const data = await res.json();
    if (data.ok) {
      statusEl.textContent = `✅ ${data.message} (${data.elapsed_ms} ms)`;
      statusEl.classList.add("ok");
    } else {
      statusEl.textContent = `⛔ ${data.message}${data.hint ? " — " + data.hint : ""}`;
      statusEl.classList.add("err");
    }
  } catch (err) {
    statusEl.textContent = "⛔ Impossible de lancer le test.";
    statusEl.classList.add("err");
  }
}

async function refreshBridgeUI() {
  try {
    const cfg = await fetch("/api/bridge/config").then(r => r.json());
    state.bridgeEnabled = cfg.enabled;
    const configuredView = document.getElementById("bridge-configured-view");
    const setupView = document.getElementById("bridge-setup-view");
    const connectedBadge = document.getElementById("bridge-connected-badge");
    const disconnectedBadge = document.getElementById("bridge-disconnected-badge");

    if (cfg.configured && cfg.enabled) {
      connectedBadge.classList.remove("hidden");
      disconnectedBadge.classList.add("hidden");
      configuredView.classList.remove("hidden");
      setupView.classList.add("hidden");
      document.getElementById("bridge-repo-display").textContent =
        `${cfg.github_owner}/${cfg.github_repo}`;
    } else {
      connectedBadge.classList.add("hidden");
      disconnectedBadge.classList.remove("hidden");
      configuredView.classList.add("hidden");
      setupView.classList.remove("hidden");
      document.getElementById("bridge-qr-reveal").classList.add("hidden");
    }
  } catch (err) {
    // Bridge status is a progressive enhancement — leave the setup form visible
  }
}

function toggleProvisioningQr() {
  const reveal = document.getElementById("bridge-qr-reveal");
  const nowHidden = reveal.classList.toggle("hidden");
  if (!nowHidden) {
    document.getElementById("bridge-qr-img").src = `/api/bridge/provisioning-qr.png?t=${Date.now()}`;
  }
}

async function saveBridgeConfig() {
  const statusEl = document.getElementById("bridge-status-line");
  statusEl.className = "status-line";
  statusEl.textContent = "Vérification du dépôt...";

  const payload = {
    github_owner: document.getElementById("bridge-owner").value.trim(),
    github_repo: document.getElementById("bridge-repo").value.trim(),
    github_token: document.getElementById("bridge-token").value.trim(),
  };

  try {
    const res = await fetch("/api/bridge/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Échec de la configuration.");

    statusEl.textContent = "✅ Dépôt privé vérifié — Réseau TASHIL connecté.";
    statusEl.classList.add("ok");
    document.getElementById("bridge-token").value = "";
    showToast("🌉 Réseau TASHIL connecté", "success");
    await refreshBridgeUI();
  } catch (err) {
    statusEl.textContent = `⛔ ${err.message}`;
    statusEl.classList.add("err");
  }
}

async function importBridgeCode() {
  const statusEl = document.getElementById("bridge-status-line");
  statusEl.className = "status-line";
  statusEl.textContent = "Vérification du code...";

  const code = document.getElementById("bridge-import-input").value.trim();
  if (!code) {
    statusEl.textContent = "Veuillez coller un code de provisioning.";
    statusEl.classList.add("err");
    return;
  }

  try {
    const res = await fetch("/api/bridge/import-code", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Échec de l'import.");

    statusEl.textContent = "✅ Réseau TASHIL connecté.";
    statusEl.classList.add("ok");
    document.getElementById("bridge-import-input").value = "";
    showToast("🌉 Réseau TASHIL connecté", "success");
    await refreshBridgeUI();
  } catch (err) {
    statusEl.textContent = `⛔ ${err.message}`;
    statusEl.classList.add("err");
  }
}

async function disableBridge() {
  if (!confirm("Désactiver le Réseau TASHIL ? Les messages en attente distants ne seront plus relevés.")) {
    return;
  }
  await fetch("/api/bridge/disable", { method: "POST" });
  state.bridgeEnabled = false;
  showToast("🚫 Réseau TASHIL désactivé", "info");
  await refreshBridgeUI();
}

async function pollBridge(manual) {
  if (!state.bridgeEnabled) return;
  try {
    const res = await fetch("/api/bridge/poll", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      if (manual) showToast(`⛔ ${data.error || "Échec de la vérification distante."}`, "error");
      return;
    }
    if (data.new_messages > 0) {
      showToast(`📥 ${data.new_messages} message(s) reçu(s) via le Cloud Bridge`, "success");
      showSystemNotification("TASHIL DOCUMENT HUB",
        `${data.new_messages} nouveau(x) message(s) distant(s) reçu(s)`);
      playNotificationSound();
      if (state.currentView === "dashboard") loadDashboard();
      if (state.currentView === "messagerie") loadInbox();
    } else if (manual) {
      showToast("✅ Aucun nouveau message distant.", "info");
    }

    if (data.receipts && data.receipts.length > 0) {
      data.receipts.forEach(receipt => {
        const message = `📄 Le document ${receipt.tracking_number} a été consulté / réceptionné par ${receipt.acknowledged_by}`;
        showToast(message, "success");
        showSystemNotification("TASHIL DOCUMENT HUB", message);
        playNotificationSound();
      });
      if (state.currentView === "dashboard") loadDashboard();
      if (state.currentView === "messagerie") loadInbox();
    }
  } catch (err) {
    if (manual) showToast("⛔ Impossible de contacter le Cloud Bridge.", "error");
  }
}

// ------------------------------------------------------------------ //
// Logout = lock (switch institutions without deleting anything)
// ------------------------------------------------------------------ //
function setupLogout() {
  document.getElementById("logout-btn").onclick = () => {
    if (!confirm("Verrouiller cet établissement et revenir à l'écran de sélection ?")) {
      return;
    }
    lockSession();
  };
}

// ------------------------------------------------------------------ //
// Delete profile (irreversible — requires PIN re-entry, not just a
// dismissible dialog, since this permanently destroys archived documents)
// ------------------------------------------------------------------ //
function setupDeleteProfile() {
  document.getElementById("delete-profile-btn").onclick = openDeleteProfileModal;
  document.getElementById("delete-profile-cancel-btn").onclick = closeDeleteProfileModal;
  document.getElementById("delete-profile-confirm-btn").onclick = confirmDeleteProfile;
}

function openDeleteProfileModal() {
  document.getElementById("delete-profile-institution-name").textContent =
    state.profile ? state.profile.institution_name : "";
  document.getElementById("delete-profile-pin").value = "";
  document.getElementById("delete-profile-error").classList.add("hidden");
  document.getElementById("delete-profile-overlay").classList.remove("hidden");
}

function closeDeleteProfileModal() {
  document.getElementById("delete-profile-overlay").classList.add("hidden");
}

async function confirmDeleteProfile() {
  const errorEl = document.getElementById("delete-profile-error");
  errorEl.classList.add("hidden");

  const pin = document.getElementById("delete-profile-pin").value.trim();
  if (!/^\d{4,6}$/.test(pin)) {
    errorEl.textContent = "Le code PIN doit contenir 4 à 6 chiffres.";
    errorEl.classList.remove("hidden");
    return;
  }

  let deleteData;
  try {
    const res = await fetch("/api/profile/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    });
    deleteData = await res.json();
    if (!res.ok) throw new Error(deleteData.error || "Échec de la suppression.");
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove("hidden");
    return;
  }

  // The delete itself has now genuinely succeeded — anything below this
  // point is just redirect bookkeeping and must never be reported back
  // as a deletion failure if it hiccups.
  closeDeleteProfileModal();
  if (deleteData.warning) {
    showToast(`⚠️ ${deleteData.warning}`, "error");
  } else {
    showToast("🗑️ Profil supprimé définitivement", "success");
  }

  state.profile = null;
  document.getElementById("app").classList.add("hidden");

  try {
    const session = await fetch("/api/session").then(r => r.json());
    state.session = session;
    if (session.first_launch) {
      showOnboarding({ allowCancel: false });
      return;
    }
  } catch (err) {
    // Fall through to showLockScreen() below regardless — it has its own
    // retry-capable error handling rather than leaving the user stuck.
  }
  await showLockScreen();
}

// ------------------------------------------------------------------ //
// Utils
// ------------------------------------------------------------------ //
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

boot();
