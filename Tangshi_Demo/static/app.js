function el(id) {
  return document.getElementById(id);
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderAuthors(authors) {
  const select = el("authorStyle");
  select.innerHTML = "";

  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = "不限（自动融合参考风格）";
  select.appendChild(defaultOpt);

  (authors || []).forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    select.appendChild(opt);
  });
}

function renderReferences(refs) {
  const box = el("references");
  if (!refs || !refs.length) {
    box.innerHTML = '<div class="list-empty">暂无数据</div>';
    return;
  }
  box.innerHTML = refs
    .map((item) => {
      return `<article class="item">
        <h3>《${escapeHtml(item.title)}》- ${escapeHtml(item.author)} <span class="score">score=${item.score}</span></h3>
        <p>${escapeHtml(item.content)}</p>
      </article>`;
    })
    .join("");
}

function renderRecent(poems) {
  const box = el("recentPoems");
  if (!poems || !poems.length) {
    box.innerHTML = '<div class="list-empty">暂无数据</div>';
    return;
  }
  box.innerHTML = poems
    .map((poem) => {
      return `<article class="item">
        <h3>《${escapeHtml(poem.title)}》- ${escapeHtml(poem.author)}</h3>
        <p>${escapeHtml(poem.content)}</p>
      </article>`;
    })
    .join("");
}

async function loadAuthors() {
  const resp = await fetch("/api/tangshi/authors");
  const data = await resp.json();
  if (!resp.ok || !data.success) {
    throw new Error(data.message || "加载作者失败");
  }
  renderAuthors(data.data.authors || []);
}

async function loadRecent() {
  const resp = await fetch("/api/tangshi/recent?limit=6");
  const data = await resp.json();
  if (!resp.ok || !data.success) {
    throw new Error(data.message || "加载最近诗作失败");
  }
  renderRecent(data.data.items || []);
}

async function generatePoem() {
  const btn = el("generateBtn");
  btn.disabled = true;
  el("status").textContent = "正在生成，请稍候...";

  const requirement = el("requirement").value.trim();
  const author_style = el("authorStyle").value.trim();
  const top_k = Number(el("topK").value || "5");
  if (!requirement) {
    el("status").textContent = "请先输入作诗要求";
    btn.disabled = false;
    return;
  }

  try {
    const resp = await fetch("/api/tangshi/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requirement, author_style, top_k }),
    });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
      throw new Error(data.message || "生成失败");
    }

    el("poemResult").textContent = data.data.poem || "";
    el("meta").innerHTML = [
      `<span>耗时：${data.data.elapsedMs} ms</span>`,
      `<span>LLM：${escapeHtml(data.data.models.llm)}</span>`,
      `<span>Embedding：${escapeHtml(data.data.models.embedding)}</span>`,
      `<span>格律校验：${data.data.constraintPassed ? "通过" : "未通过"}</span>`,
      `<span>重复度分数：${data.data.repetitionScore ?? "-"}</span>`,
    ].join("");
    renderReferences(data.data.references || []);
    if (!data.data.constraintPassed) {
      const msg = data.data.constraintMessage || "字数或句数未严格匹配";
      el("status").textContent = `生成完成（提示：${msg}）`;
    } else if (data.data.repetitionMessage) {
      el("status").textContent = `生成成功（提示：${data.data.repetitionMessage}）`;
    } else {
      el("status").textContent = "生成成功";
    }
  } catch (err) {
    el("status").textContent = `生成失败：${err.message || err}`;
  } finally {
    btn.disabled = false;
  }
}

async function bootstrap() {
  el("status").textContent = "初始化中...";
  try {
    await Promise.all([loadAuthors(), loadRecent()]);
    el("status").textContent = "就绪";
  } catch (err) {
    el("status").textContent = `初始化失败：${err.message || err}`;
  }
}

el("generateBtn").addEventListener("click", generatePoem);
el("refreshRecentBtn").addEventListener("click", loadRecent);
bootstrap();
