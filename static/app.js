async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  });
  return res.json();
}

function setText(id, text) {
  document.getElementById(id).textContent = text || "";
}

function setHtml(id, html) {
  document.getElementById(id).innerHTML = html || "";
}

function renderPlot(targetId, plotJson) {
  if (!plotJson) return;
  const fig = JSON.parse(plotJson);
  Plotly.newPlot(targetId, fig.data || [], fig.layout || {}, { responsive: true, displaylogo: false });
}

function setBusy(btn, busy) {
  btn.disabled = busy;
  btn.style.opacity = busy ? "0.6" : "1";
}

document.getElementById("setupBtn").addEventListener("click", async (e) => {
  const btn = e.target;
  setBusy(btn, true);
  setText("setupStatus", "Running setup...");
  const data = await postJson("/api/setup", {});
  setText("setupStatus", data.message || "");
  setText("setupLog", (data.log || []).join("\n"));
  setBusy(btn, false);
});

document.getElementById("compareBtn").addEventListener("click", async (e) => {
  const btn = e.target;
  setBusy(btn, true);
  setText("compareStatus", "Capturing traces...");
  const data = await postJson("/api/compare", {
    correct: document.getElementById("compareCorrect").value,
    wrong: document.getElementById("compareWrong").value
  });
  setText("compareStatus", data.message || "");
  renderPlot("comparePlot", data.plot_json);
  setBusy(btn, false);
});

document.getElementById("sweepBtn").addEventListener("click", async (e) => {
  const btn = e.target;
  setBusy(btn, true);
  setText("sweepStatus", "Running sweep...");
  const data = await postJson("/api/sweep", {
    prefix: document.getElementById("sweepPrefix").value,
    samples: Number(document.getElementById("sweepSamples").value)
  });
  setText("sweepStatus", data.message || "");
  renderPlot("sweepPlot", data.plot_json);
  setBusy(btn, false);
});

document.getElementById("diffBtn").addEventListener("click", async (e) => {
  const btn = e.target;
  setBusy(btn, true);
  setText("diffStatus", "Computing difference traces...");
  const data = await postJson("/api/diff", {
    prefix: document.getElementById("diffPrefix").value,
    samples: Number(document.getElementById("diffSamples").value)
  });
  setText("diffStatus", data.message || "");
  renderPlot("diffPlot", data.plot_json);
  setBusy(btn, false);
});

document.getElementById("quantBtn").addEventListener("click", async (e) => {
  const btn = e.target;
  setBusy(btn, true);
  setText("quantStatus", "Scoring all candidates...");
  const data = await postJson("/api/quant", {
    prefix: document.getElementById("quantPrefix").value
  });
  setText("quantStatus", data.message || "");
  if (data.winner) {
    setText("winner", `Winner: ${data.winner} (score=${data.winner_score})`);
  }
  renderPlot("quantPlot", data.plot_json);
  setBusy(btn, false);
});

document.getElementById("attackBtn").addEventListener("click", async (e) => {
  const btn = e.target;
  setBusy(btn, true);
  setText("attackStatus", "Running full attack...");
  const data = await postJson("/api/attack", {
    length: Number(document.getElementById("attackLength").value)
  });
  setText("attackStatus", data.message || "");
  if (data.password) {
    setText("passwordOut", data.password);
  }
  setText("attackLog", (data.log || []).join("\n"));
  setBusy(btn, false);
});

// ── Simulation: set demo password ────────────────────────────────────────────
const simPwBtn = document.getElementById("simPwBtn");
if (simPwBtn) {
  simPwBtn.addEventListener("click", async (e) => {
    const btn    = e.target;
    const input  = document.getElementById("simPwInput");
    const status = document.getElementById("simPwStatus");
    setBusy(btn, true);
    status.textContent = "";
    status.className   = "sim-pw-status";

    const data = await postJson("/api/set_password", { password: input.value });

    if (data.ok) {
      // Update the Step 6 length hint in the banner
      const lenSpan = document.getElementById("simPwLen");
      if (lenSpan) lenSpan.textContent = data.length;
      status.textContent = `✔ ${data.message}`;
      status.classList.add("sim-pw-ok");
    } else {
      status.textContent = `✘ ${data.message}`;
      status.classList.add("sim-pw-err");
    }
    setBusy(btn, false);
  });
}
