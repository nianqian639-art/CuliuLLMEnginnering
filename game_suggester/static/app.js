function el(id) {
  return document.getElementById(id);
}

function toHtml(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderSnapshot(meta) {
  if (!meta) {
    el("snapshot").innerHTML = '<div class="empty">暂无数据</div>';
    return;
  }
  const lines = [
    ["roomCode", meta.roomCode],
    ["gameId", meta.gameId],
    ["rulesVersion", meta.rulesVersion],
    ["status", meta.status],
    ["board", `${meta.rows} x ${meta.cols}`],
    ["occupiedCells", meta.occupiedCells],
    ["currentTurn", meta.currentTurn],
    ["player1", `${meta.player1} (score: ${meta.player1Score})`],
    ["player2", `${meta.player2} (score: ${meta.player2Score})`],
  ];
  el("snapshot").innerHTML = lines
    .map(([k, v]) => `<div class="kv"><div>${toHtml(k)}</div><div>${toHtml(v)}</div></div>`)
    .join("");
}

function renderBest(result) {
  if (!result || !result.bestSuggestion) {
    el("best").innerHTML = '<div class="empty">暂无数据</div>';
    return;
  }
  const best = result.bestSuggestion;
  const c = best.candidate;
  const e = best.evaluation;
  const legalTag = e.isLegal ? '<span class="ok">合法</span>' : '<span class="warn">不合法</span>';

  el("best").innerHTML = [
    `<div class="kv"><div>Prompt版本</div><div>${toHtml(result.promptVersion || "default")}</div></div>`,
    `<div class="kv"><div>位置</div><div>row=${c.row}, col=${c.col}</div></div>`,
    `<div class="kv"><div>输入值</div><div>${toHtml(c.value)}</div></div>`,
    `<div class="kv"><div>来源</div><div>${toHtml(c.source)}</div></div>`,
    `<div class="kv"><div>合法性</div><div>${legalTag}</div></div>`,
    `<div class="kv"><div>建议理由</div><div>${toHtml(c.reason)}</div></div>`,
    `<div class="kv"><div>风险提示</div><div>${toHtml(c.risk)}</div></div>`,
    `<div class="kv"><div>评估说明</div><div>${toHtml(e.reason)}</div></div>`,
    `<div class="kv"><div>分数变化</div><div>p1=${e.scoreDelta?.player1 ?? 0}, p2=${e.scoreDelta?.player2 ?? 0}</div></div>`,
    `<div class="kv"><div>下一回合</div><div>${toHtml(e.nextTurn)}</div></div>`,
    `<div class="kv"><div>置信度</div><div>${best.confidence ?? "-"}</div></div>`,
  ].join("");
}

function renderAlternatives(result) {
  const alts = result?.alternatives || [];
  if (!alts.length) {
    el("alts").innerHTML = '<div class="empty">暂无备选</div>';
    return;
  }
  el("alts").innerHTML = `<ul>${alts
    .map((item) => {
      const c = item.candidate;
      const e = item.evaluation;
      return `<li>(r${c.row}, c${c.col}) value=${toHtml(c.value)} | ${toHtml(c.reason)} | delta(p1=${e.scoreDelta?.player1 ?? 0}, p2=${e.scoreDelta?.player2 ?? 0})</li>`;
    })
    .join("")}</ul>`;
}

function renderWarnings(result) {
  const warnings = result?.warnings || [];
  if (!warnings.length) {
    el("warnings").innerHTML = '<div class="ok">无告警</div>';
    return;
  }
  el("warnings").innerHTML = `<ul>${warnings.map((w) => `<li class="warn">${toHtml(w)}</li>`).join("")}</ul>`;
}

async function runSuggest() {
  const btn = el("runBtn");
  btn.disabled = true;
  el("status").textContent = "请求中...";

  const payload = {
    gameBaseUrl: el("gameBaseUrl").value.trim(),
    username: el("username").value.trim(),
    password: el("password").value,
    roomCode: el("roomCode").value.trim(),
    model: el("model").value.trim(),
    promptVersion: el("promptVersion").value.trim() || "default",
    maxCandidates: Number(el("maxCandidates").value || "6"),
  };

  try {
    const resp = await fetch("/api/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    el("raw").textContent = JSON.stringify(data, null, 2);

    renderSnapshot(data.snapshotMeta);
    renderBest(data);
    renderAlternatives(data);
    renderWarnings(data);

    if (resp.ok && data.success) {
      el("status").textContent = `完成：共评估 ${data.candidateCount} 条候选`;
    } else {
      el("status").textContent = `失败：${data.message || "unknown error"}`;
    }
  } catch (err) {
    el("status").textContent = `请求异常：${err}`;
  } finally {
    btn.disabled = false;
  }
}

async function loadPromptVersions() {
  try {
    const resp = await fetch("/api/prompt_versions");
    const data = await resp.json();
    if (!resp.ok || !data.success) {
      return;
    }
    const list = el("promptVersionsList");
    list.innerHTML = "";
    (data.versions || []).forEach((version) => {
      const opt = document.createElement("option");
      opt.value = version;
      list.appendChild(opt);
    });
    if (!el("promptVersion").value && data.default) {
      el("promptVersion").value = data.default;
    }
  } catch (_err) {
    // keep default if fetch fails
  }
}

el("runBtn").addEventListener("click", runSuggest);
loadPromptVersions();
