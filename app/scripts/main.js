/* ============================================================
   Blood Banking Antibody ID — Frontend controller
   Plain browser JS (no framework, no Node/require). Talks to the `abid`
   engine through a local HTTP API (the flask bridge shipped in the app).
   Used both as file:// pages and as a served app.
   ============================================================ */

(() => {
  "use strict";

  // --- DOM refs ---
  const $ = (id) => document.getElementById(id);

  const patientIdInput = $("patient-id");
  const serumInput = $("serum");
  const antigramInput = $("antigram-json");
  const btnAnalyze = $("btn-analyze");
  const btnLoadK = $("btn-load-k");
  const btnLoadK2 = $("btn-load-k2");
  const btnLoadAuto = $("btn-load-auto");

  const viewResult = $("view-result");
  const viewHistory = $("view-history");
  const viewSettings = $("view-settings");
  const resultNote = $("result-note");
  const resultContent = $("result-content");

  const identityBody = $("identity-body");
  const exclusionsBody = $("exclusions-body");
  const pairsBody = $("pairs-body");
  const flagsList = $("flags-list");
  const statusBadge = $("result-badge");

  const historyList = $("history-list");
  const historyBody = $("history-body");

  // --- State ---
  let history = [];
  let lastResult = null;

  // Local Flask bridge path (served by the console launcher).
  const BRIDGE = "http://127.0.0.1:9120";

  // --- Engine runner (HTTP API) ---
  async function runEngine(args, inputText) {
    // Send the input JSON on stdin of the bridge's /analyze endpoint and
    // ask it to return the JSON envelope on stdout.
    const res = await fetch(`${BRIDGE}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        patient_id: args[0],
        serum: args[1],
        json: "--json",
        payload: inputText,
      }),
    });
    if (!res.ok) {
      const msg = await res.text().catch(() => "");
      throw new Error(`engine HTTP ${res.status}: ${msg || "unknown"}`);
    }
    return { stdout: await res.text() };
  }

  // --- Navigation ---
  document.querySelectorAll(".sidebar__nav-item").forEach((item) => {
    item.addEventListener("click", (e) => {
      e.preventDefault();
      document.querySelectorAll(".sidebar__nav-item").forEach((i) => i.classList.remove("--active"));
      item.classList.add("--active");
      const view = item.dataset.view;
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("--active"));
      const target = document.getElementById(`view-${view}`);
      if (target) target.classList.add("--active");
    });
  });

  // --- Tabs ---
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("--active"));
      btn.classList.add("--active");
      const tab = btn.dataset.tab;
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("--active"));
      const el = document.getElementById(`tab-${tab}`);
      if (el) el.classList.add("--active");
    });
  });

  // --- Load sample antigrams ---
  function setAntigramSample(json) {
    antigramInput.value = JSON.stringify(json, null, 2);
  }

  btnLoadK.addEventListener("click", () => {
    setAntigramSample({
      patient_id: "PT-K1",
      serum: "serum-A",
      cells: { C1: ["K"], C2: ["K"], C3: ["K"], C4: ["K"], C5: ["K"] },
      reactions: { C1: { grade: 3 }, C2: { grade: 3 }, C3: { grade: 3 }, C4: { grade: 3 }, C5: { grade: 3 } }
    });
    patientIdInput.value = "PT-K1";
    serumInput.value = "serum-A";
  });

  btnLoadK2.addEventListener("click", () => {
    setAntigramSample({
      patient_id: "PT-E+K",
      serum: "serum-D",
      cells: {
        C1: ["E", "K"], C2: ["E", "K"], C3: ["E", "K"], C4: ["E", "K"], C5: ["E", "K"],
        C6: ["E"], C7: ["K"], C8: ["e", "k"]
      },
      reactions: {
        C1: { grade: 3 }, C2: { grade: 3 }, C3: { grade: 3 }, C4: { grade: 3 }, C5: { grade: 3 },
        C6: { grade: 2 }, C7: { grade: 2 }, C8: { grade: 0 }
      }
    });
    patientIdInput.value = "PT-E+K";
    serumInput.value = "serum-D";
  });

  btnLoadAuto.addEventListener("click", () => {
    setAntigramSample({
      patient_id: "PT-AC1",
      serum: "serum-X",
      cells: {
        C1: ["K"], C2: ["K"], C3: ["D"], C4: ["k"], C5: ["e"]
      },
      reactions: {
        C1: { grade: 3 }, C2: { grade: 3 }, C3: { grade: 3, autocontrol: true },
        C4: { grade: 1 }, C5: { grade: 1 }
      }
    });
    patientIdInput.value = "PT-AC1";
    serumInput.value = "serum-X";
  });

  // --- Analyze ---
  btnAnalyze.addEventListener("click", async () => {
    btnAnalyze.disabled = true;
    btnAnalyze.textContent = "Analyzing...";

    try {
      const patientId = patientIdInput.value.trim() || "unknown";
      const serumVal = serumInput.value.trim() || "serum";
      const raw = antigramInput.value;

      let data;
      try {
        data = JSON.parse(raw);
      } catch (e) {
        resultNote.textContent = "Invalid JSON in antigram editor. Check for mismatched braces or quotes.";
        resultNote.className = "alert alert--info";
        resultNote.hidden = false;
        resultContent.hidden = true;
        historyList.hidden = true;
        return;
      }

      const pid = data.patient_id || patientId;

      // Normalize cells/reactions to the engine's expected format.
      const cells = data.cells || {};
      const reactions = data.reactions || {};

      // Build the payload the engine expects (envelope + cells + reactions).
      const payload = JSON.stringify({
        patient_id: pid,
        serum: serumVal,
        cells: Object.fromEntries(
          Object.entries(cells).map(([cid, antigens]) => [
            cid,
            Array.isArray(antigens) ? antigens : [antigens]
          ])
        ),
        reactions: Object.fromEntries(
          Object.entries(reactions).map(([cid, r]) => [
            cid,
            { grade: Number(r.grade) || 0, autocontrol: Boolean(r.autocontrol) }
          ])
        ),
      });

      // The Flask bridge (app/console.py) runs the engine and returns the JSON
      // envelope as its response body.
      const { stdout, stderr } = await runEngine(
        ["-p", pid, "-a", "-", "--json"],
        payload
      );
      if (stderr) console.warn("engine stderr:", stderr);

      let res;
      try {
        res = JSON.parse(stdout.trim());
      } catch (e) {
        resultNote.textContent = "Engine returned invalid JSON. Check the panel data.";
        resultNote.className = "alert alert--info";
        resultContent.hidden = true;
        return;
      }

      if (!res || res.identity === undefined) {
        resultNote.textContent = "Engine returned unexpected output format.";
        resultNote.className = "alert alert--info";
        resultContent.hidden = true;
        return;
      }

      lastResult = res;
      renderResult(res);
      pushHistory(res);
    } catch (err) {
      resultNote.textContent = `Engine error: ${err.message}`;
      resultNote.className = "alert alert--info";
      console.error(err);
    } finally {
      btnAnalyze.disabled = false;
      btnAnalyze.textContent = "Analyze Panel";
    }
  });

  // --- Render result ---
  function renderResult(res) {
    const header = resultContent.querySelector(".result__header");
    if (res.single_antibody) {
      header.querySelector("h2").textContent = res.single_antibody;
    } else {
      header.querySelector("h2").textContent = "No antibody identified";
    }
    header.querySelector(".result__score").textContent =
      `confidence ${res.single_score.toFixed(3)} · ${res.identity.length} cells checked`;

    // Badge
    const badge = statusBadge;
    if (res.auto_control_positive) {
      badge.className = "badge badge--auto";
      badge.textContent = "AUTO-CONTROL POSITIVE";
    } else if (res.confident_single && res.single_antibody) {
      badge.className = "badge badge--confident";
      badge.textContent = "CONFIDENT";
    } else if (res.confident_single) {
      badge.className = "badge badge--weak";
      badge.textContent = "REQUIRES REVIEW";
    } else {
      badge.className = "badge badge--inconclusive";
      badge.textContent = "INCONCLUSIVE";
    }

    // Identity table
    identityBody.innerHTML = "";
    for (const row of res.identity) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${row.cell_id}</td>
        <td>${row.phenotype}</td>
        <td class="mono">${row.grade}</td>
        <td class="status ${row.status}">${row.status}</td>
      `;
      identityBody.appendChild(tr);
    }

    // Exclusions
    exclusionsBody.innerHTML = "";
    if (res.single_exclusions && res.single_exclusions.length) {
      for (const ex of res.single_exclusions) {
        const li = document.createElement("li");
        li.textContent = ex;
        exclusionsBody.appendChild(li);
      }
    } else {
      exclusionsBody.innerHTML = "<li>None — no antigen-exclusion conflicts detected.</li>";
    }

    // Pairs
    pairsBody.innerHTML = "";
    if (res.pairs && res.pairs.length) {
      for (const p of res.pairs) {
        const tr = document.createElement("tr");
        const statusClass = p.status === "confident" ? "status--confident" : "status--review";
        tr.innerHTML = `
          <td>${p.pair[0]} + ${p.pair[1]}</td>
          <td class="mono">${p.score.toFixed(3)}</td>
          <td class="status ${statusClass}">${p.status === "confident" ? "CONFIDENT" : "REVIEW"}</td>
        `;
        pairsBody.appendChild(tr);
      }
    } else {
      pairsBody.innerHTML = "<tr><td colspan='3'>No two-antibody combination detected.</td></tr>";
    }

    // Flags
    flagsList.innerHTML = "";
    for (const f of res.flagged) {
      const li = document.createElement("li");
      li.textContent = f;
      flagsList.appendChild(li);
    }
  }

  // --- History ---
  function pushHistory(res) {
    const now = new Date().toISOString().replace("T", " ").slice(0, 19);
    history.push({
      patient_id: res.patient_id,
      date: now,
      single: res.single_antibody || "none",
      pairs: res.pairs && res.pairs.length ? res.pairs.map((p) => p.pair.join(" + ")).join(", ") : "—",
      status: res.auto_control_positive ? "auto-control" : (res.confident_single ? "confident" : "review"),
    });
    historyList.hidden = false;
    historyBody.innerHTML = "";
    for (const h of history) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${h.patient_id}</td>
        <td class="mono">${h.date}</td>
        <td>${h.single}</td>
        <td>${h.pairs}</td>
        <td class="status ${h.status === "confident" ? "status--confident" : h.status === "auto-control" ? "status--auto" : "status--review"}">${h.status}</td>
      `;
      historyBody.appendChild(tr);
    }
  }

  // --- Init ---
  antigramInput.value = JSON.stringify({
    patient_id: "PT-K1",
    serum: "serum-A",
    cells: { C1: ["K"], C2: ["K"], C3: ["K"], C4: ["K"], C5: ["K"] },
    reactions: { C1: { grade: 3 }, C2: { grade: 3 }, C3: { grade: 3 }, C4: { grade: 3 }, C5: { grade: 3 } }
  }, null, 2);
  patientIdInput.value = "PT-K1";
  serumInput.value = "serum-A";

  // Load the anti-K panel on startup.
  btnLoadK.click();

})();
