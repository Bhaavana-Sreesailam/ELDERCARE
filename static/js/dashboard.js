/* =========================================================================
   ElderCare Guardian — dashboard logic

   Polls the backend for the latest reading and alerts, then drives the
   status panel, stat cards, alert log and trend chart. The status panel's
   colour and headline are derived from active alerts + heart-rate bands.
   ========================================================================= */

const POLL_MS = 3000;          // how often to refresh the live view
let chart = null;
let currentHours = 6;          // trend range, matches the active toggle

// ---- Helpers -------------------------------------------------------------
function timeAgo(iso) {
  if (!iso) return "—";
  const secs = Math.max(0, (Date.now() - new Date(iso + "Z").getTime()) / 1000);
  if (secs < 5) return "just now";
  if (secs < 60) return `${Math.floor(secs)}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

function fmt(v, digits = 0) {
  return (v === null || v === undefined) ? "—" : Number(v).toFixed(digits);
}

// ---- Status panel --------------------------------------------------------
function applyStatus(reading, activeAlerts) {
  const panel = document.getElementById("status-panel");
  const headline = document.getElementById("status-headline");
  const detail = document.getElementById("status-detail");

  // Decide overall state from active alerts first, then the live HR.
  let state = "ok";
  const hasEmergency = activeAlerts.some(a => a.severity === "emergency");
  const hasWarning = activeAlerts.some(a => a.severity === "warning");

  if (hasEmergency) state = "emergency";
  else if (hasWarning) state = "warn";

  if (!reading) {
    state = "unknown";
    headline.textContent = "Connecting…";
    detail.textContent = "Waiting for the first reading from the wearable.";
  } else if (state === "emergency") {
    const a = activeAlerts.find(x => x.severity === "emergency");
    headline.textContent = "Emergency";
    detail.textContent = a ? a.message : "An emergency condition was detected.";
  } else if (state === "warn") {
    const a = activeAlerts.find(x => x.severity === "warning");
    headline.textContent = "Needs attention";
    detail.textContent = a ? a.message : "A reading is outside the normal range.";
  } else {
    headline.textContent = "All is well";
    detail.textContent = "Heart rate is in range and no falls detected.";
  }

  panel.className = "status-panel state-" + state;
}

// ---- Live tick (current reading + alerts) --------------------------------
async function refreshCurrent() {
  try {
    const res = await fetch("/api/current");
    const data = await res.json();

    const reading = data.reading;
    const active = data.active_alerts || [];
    const s = data.summary || {};

    // Big number + pulse
    document.getElementById("bpm-value").textContent =
      reading && reading.heart_rate ? fmt(reading.heart_rate) : "––";
    document.getElementById("last-seen").textContent =
      reading ? timeAgo(reading.timestamp) : "—";
    if (data.patient) {
      document.getElementById("patient-name").textContent = data.patient.name;
    }

    // Stat cards
    document.getElementById("stat-resting").textContent = fmt(s.hr_resting);
    document.getElementById("stat-range").textContent =
      (s.hr_min && s.hr_max) ? `${fmt(s.hr_min)}–${fmt(s.hr_max)}` : "—";
    document.getElementById("stat-wellness").textContent = fmt(s.wellness);
    document.getElementById("stat-motion").textContent =
      reading ? motionLabel(reading.accel_magnitude) : "—";

    applyStatus(reading, active);
    renderAlertList(active, /* isActiveOnly */ true);

    // Active count badge
    const badge = document.getElementById("alert-count");
    badge.textContent = `${active.length} active`;
    badge.classList.toggle("has-active", active.length > 0);
  } catch (err) {
    console.error("refreshCurrent failed", err);
  }
}

function motionLabel(mag) {
  if (mag === null || mag === undefined) return "—";
  if (mag > 2.6) return "impact";
  if (mag < 0.45) return "free-fall";
  if (Math.abs(mag - 1) < 0.18) return "resting";
  return "active";
}

// ---- Alert log -----------------------------------------------------------
async function refreshAlertLog() {
  try {
    const res = await fetch("/api/alerts");
    const data = await res.json();
    renderAlertList(data.alerts || [], false);
  } catch (err) {
    console.error("refreshAlertLog failed", err);
  }
}

function renderAlertList(alerts, activeOnly) {
  // The live tick renders active alerts; the full log renders all.
  // We only repaint the list from the full log to avoid flicker, but show
  // a friendly empty state in either case.
  if (activeOnly) return;  // full-log refresh owns the list rendering

  const list = document.getElementById("alert-list");
  if (!alerts.length) {
    list.innerHTML = `<p class="empty-note">No alerts recorded yet.</p>`;
    return;
  }

  list.innerHTML = alerts.map(a => {
    const sev = a.severity === "emergency" ? "emergency"
              : a.severity === "warning" ? "warning" : "info";
    const resolvedCls = a.resolved ? " is-resolved" : "";
    const resolveBtn = a.resolved
      ? `<span class="alert-time">resolved</span>`
      : `<button class="alert-resolve" data-id="${a.id}">Mark resolved</button>`;
    return `
      <div class="alert-item sev-${sev}${resolvedCls}">
        <span class="alert-tag">${sev}</span>
        <div class="alert-body">
          <p class="alert-msg">${escapeHtml(a.message)}</p>
          <p class="alert-time">${timeAgo(a.timestamp)} · ${escapeHtml(a.alert_type)}</p>
        </div>
        ${resolveBtn}
      </div>`;
  }).join("");

  list.querySelectorAll(".alert-resolve").forEach(btn => {
    btn.addEventListener("click", async () => {
      await fetch(`/api/alerts/${btn.dataset.id}/resolve`, { method: "POST" });
      refreshAlertLog();
      refreshCurrent();
    });
  });
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

// ---- Trend chart ---------------------------------------------------------
async function refreshChart() {
  try {
    const res = await fetch(`/api/history?hours=${currentHours}`);
    const data = await res.json();
    const trend = data.hourly || { labels: [], values: [] };

    if (!chart) {
      const ctx = document.getElementById("hrChart").getContext("2d");
      const grad = ctx.createLinearGradient(0, 0, 0, 300);
      grad.addColorStop(0, "rgba(79,122,106,.22)");
      grad.addColorStop(1, "rgba(79,122,106,0)");

      chart = new Chart(ctx, {
        type: "line",
        data: {
          labels: trend.labels,
          datasets: [{
            label: "Heart rate (bpm)",
            data: trend.values,
            borderColor: "#4f7a6a",
            backgroundColor: grad,
            borderWidth: 2.5,
            tension: 0.35,
            fill: true,
            pointRadius: 0,
            pointHoverRadius: 5,
            pointHoverBackgroundColor: "#3a5b4f",
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { intersect: false, mode: "index" },
          plugins: { legend: { display: false } },
          scales: {
            y: {
              grid: { color: "rgba(43,39,34,.06)" },
              ticks: { color: "#6f675d" },
              title: { display: true, text: "bpm", color: "#6f675d" },
            },
            x: {
              grid: { display: false },
              ticks: { color: "#6f675d", maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
            },
          },
        },
      });
    } else {
      chart.data.labels = trend.labels;
      chart.data.datasets[0].data = trend.values;
      chart.update("none");
    }
  } catch (err) {
    console.error("refreshChart failed", err);
  }
}

// ---- Range toggle --------------------------------------------------------
document.querySelectorAll(".range-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".range-btn").forEach(b => b.classList.remove("is-active"));
    btn.classList.add("is-active");
    currentHours = parseInt(btn.dataset.hours, 10);
    refreshChart();
  });
});

// ---- Kick everything off -------------------------------------------------
refreshCurrent();
refreshAlertLog();
refreshChart();

setInterval(refreshCurrent, POLL_MS);
setInterval(refreshAlertLog, POLL_MS * 2);
setInterval(refreshChart, 30000);   // chart changes slowly; refresh less often
