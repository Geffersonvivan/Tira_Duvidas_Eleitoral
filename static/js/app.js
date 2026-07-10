"use strict";

// Marca do assistente (balão + check) para os avatares gerados dinamicamente.
const MARCA_SVG =
  '<svg viewBox="0 0 32 32"><path d="M8 9.5 h16 a1.8 1.8 0 0 1 1.8 1.8 v6.4 a1.8 1.8 0 0 1 -1.8 1.8 h-8 l-4.5 3.2 v-3.2 h-3.5 a1.8 1.8 0 0 1 -1.8 -1.8 v-6.4 a1.8 1.8 0 0 1 1.8 -1.8 z" fill="none" stroke="#fff" stroke-width="1.9" stroke-linejoin="round"/><path d="M11.5 14.4 l2.4 2.4 L20 11.2" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';

// CSRF: lê o cookie definido pela view (ensure_csrf_cookie).
function csrftoken() {
  const m = document.cookie.match(/csrftoken=([^;]+)/);
  return m ? m[1] : "";
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

// ---------------------------------------------------------------- abas
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const alvo = tab.dataset.tab;
    document.querySelectorAll(".tab").forEach((t) =>
      t.setAttribute("aria-selected", String(t.dataset.tab === alvo))
    );
    document.querySelectorAll(".panel").forEach((p) => {
      p.hidden = p.dataset.panel !== alvo;
    });
  });
});

// ------------------------------------------------------- Serviço 1: perguntas
const chat = document.getElementById("chat");
const q = document.getElementById("q");
const btn = document.getElementById("btn-perguntar");

// Rola a lista de mensagens (o container), não a página inteira.
function rolar() {
  chat.scrollTop = chat.scrollHeight;
}

document.querySelectorAll(".chip[data-fill]").forEach((c) =>
  c.addEventListener("click", () => {
    q.value = c.dataset.fill;
    q.focus();
  })
);

function bolhaUsuario(texto) {
  chat.insertAdjacentHTML(
    "beforeend",
    `<div class="msg"><div class="avatar user">Dr</div><div class="bubble">
       <div class="who">Você</div><div class="body"><p>${esc(texto)}</p></div></div></div>`
  );
}

function fontesHTML(fontes) {
  if (!fontes || !fontes.length) return "";
  const linhas = fontes
    .map(
      (f) =>
        `<div class="src"><span class="tag ${esc(f.tipo)}">${
          f.tipo === "jurisprudencia" ? "Jurisprudência" : "Norma"
        }</span><span class="cite">${esc(f.titulo)}${
          f.vigente ? " · vigente" : ""
        }</span></div>`
    )
    .join("");
  return `<div class="sources"><h4>Fontes (norma e jurisprudência válidas)</h4>${linhas}</div>`;
}

function bolhaResposta(data) {
  let corpo;
  if (!data.on_topic) {
    corpo = `<div class="offtopic">${esc(data.texto)}</div>`;
  } else {
    corpo = `<div class="body"><p>${esc(data.texto).replace(/\n/g, "<br>")}</p></div>
      ${fontesHTML(data.fontes)}
      ${data.disclaimer ? `<div class="disclaimer">${esc(data.disclaimer)}</div>` : ""}`;
  }
  chat.insertAdjacentHTML(
    "beforeend",
    `<div class="msg"><div class="avatar bot">${MARCA_SVG}</div><div class="bubble">
       <div class="who">Tira-Dúvidas${
         data.assunto ? " · " + esc(data.assunto) : ""
       }</div>${corpo}</div></div>`
  );
  rolar();
}

async function perguntar() {
  const texto = q.value.trim();
  if (!texto) return;
  bolhaUsuario(texto);
  q.value = "";
  btn.disabled = true;
  rolar();
  const carregando = document.createElement("div");
  carregando.className = "spinner";
  carregando.textContent = "Consultando…";
  chat.appendChild(carregando);
  rolar();
  try {
    const r = await fetch("/api/perguntas/perguntar/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrftoken() },
      body: JSON.stringify({ pergunta: texto }),
    });
    const data = await r.json();
    carregando.remove();
    if (!r.ok) {
      chat.insertAdjacentHTML("beforeend", `<div class="disclaimer">Erro ao consultar. Tente novamente.</div>`);
      return;
    }
    bolhaResposta(data);
  } catch (e) {
    carregando.remove();
    chat.insertAdjacentHTML("beforeend", `<div class="disclaimer">Falha de conexão.</div>`);
  } finally {
    btn.disabled = false;
    rolar();
  }
}

btn.addEventListener("click", perguntar);
q.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    perguntar();
  }
});

// ------------------------------------------------------- Serviço 2: material
const drop = document.getElementById("drop");
const file = document.getElementById("file");
const painel = document.getElementById("pareceres");

drop.addEventListener("click", () => file.click());
file.addEventListener("change", () => {
  if (file.files.length) analisar(file.files);
});

function pontosHTML(pontos) {
  if (!pontos || !pontos.length) return "";
  return pontos
    .map((p) => {
      const cls = p.conforme === true ? "m-true" : p.conforme === false ? "m-false" : "m-null";
      const mark = p.conforme === true ? "✓" : p.conforme === false ? "!" : "?";
      return `<div class="check"><span class="mark ${cls}">${mark}</span>
        <span class="det">${esc(p.descricao)}${
          p.fundamento ? `<span class="fund">Fundamento: ${esc(p.fundamento)}</span>` : ""
        }</span></div>`;
    })
    .join("");
}

function pareceresHTML(res) {
  if (!res.on_topic) {
    return `<div class="card parecer"><div class="offtopic">${esc(res.mensagem)}</div>
      <div class="peca-head"><span class="pname">${esc(res.peca)}</span></div></div>`;
  }
  const labels = { conforme: "✓ Em conformidade", parcial: "⚠ Conformidade parcial", nao_conforme: "✕ Não conforme", inconclusivo: "? Inconclusivo" };
  return `<div class="card parecer">
    <div class="peca-head">
      <span class="status-badge st-${esc(res.status)}">${labels[res.status] || res.status}</span>
      <span class="pname">${esc(res.peca)}</span>
    </div>
    ${pontosHTML(res.pontos)}
    ${res.recomendacoes ? `<div class="sources"><h4>Recomendações</h4><div class="body" style="font-size:14px">${esc(res.recomendacoes)}</div></div>` : ""}
    ${fontesHTML(res.fontes)}
    ${res.disclaimer ? `<div class="disclaimer">${esc(res.disclaimer)}</div>` : ""}
  </div>`;
}

async function analisar(files) {
  painel.innerHTML = `<div class="spinner">Analisando ${files.length} peça(s)…</div>`;
  const fd = new FormData();
  for (const f of files) fd.append("arquivos", f);
  try {
    const r = await fetch("/api/materiais/analisar/", {
      method: "POST",
      headers: { "X-CSRFToken": csrftoken() },
      body: fd,
    });
    const data = await r.json();
    if (!r.ok) {
      painel.innerHTML = `<div class="card parecer"><div class="disclaimer">${esc(
        (data.arquivos && data.arquivos[0]) || "Não foi possível analisar."
      )}</div></div>`;
      return;
    }
    painel.innerHTML = data.resultados.map(pareceresHTML).join("");
  } catch (e) {
    painel.innerHTML = `<div class="card parecer"><div class="disclaimer">Falha de conexão.</div></div>`;
  } finally {
    file.value = "";
  }
}
