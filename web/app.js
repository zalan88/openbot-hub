"use strict";
// OpenBot Hub: vanilla JS, no build. All text from apps is set with textContent (message text is untrusted).
const $ = (s) => document.querySelector(s);
const view = $("#view"), tabs = $("#tabs"), title = $("#title"), back = $("#back");
let HUB = { name: "Hub", apps: [] };

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : String(kid));
  return el;
}
const toast = (msg) => { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 2600); };
async function api(path, body) {
  const opt = body ? { method: "POST", headers: { "Content-Type": "application/json", "X-Hub": "1" }, body: JSON.stringify(body) } : {};
  const r = await fetch("/api/" + path, { cache: "no-store", ...opt });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.refused || j.error || "erro " + r.status);
  return j;
}
const initials = (s) => (s || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
const fmtNum = (n) => (n && n.length >= 12 ? `+${n.slice(0, 2)} ${n.slice(2, 4)} ${n.slice(4, -4)}-${n.slice(-4)}` : n);
const pill = (txt, kind = "") => h("span", { class: "pill " + kind }, txt);
const ICONS = { chat: "💬", home: "🏠", chart: "📈" };

function setTop(t, canBack) { title.textContent = t; back.hidden = !canBack; }
function setTabs(items, active) {
  tabs.replaceChildren(...items.map(([id, ico, label]) =>
    h("button", { class: id === active ? "on" : "", onclick: () => (location.hash = id) }, h("b", {}, ico), label)));
  tabs.hidden = !items.length;
}
const loading = () => view.replaceChildren(h("p", { class: "empty" }, "Carregando…"));
const fail = (e) => view.replaceChildren(h("p", { class: "empty" }, "Não deu para carregar: " + e.message));

// ---------- início ----------
function home() {
  setTop(HUB.name, false); setTabs([], "");
  if (!HUB.apps.length) return view.replaceChildren(h("p", { class: "empty" }, "Nenhum app ligado na configuração."));
  view.replaceChildren(h("div", { class: "grid" }, HUB.apps.map((a) =>
    h("button", { class: "tile", onclick: () => (location.hash = "#/" + a.id) },
      h("div", { class: "ico" }, ICONS[a.icon] || "▣"), h("b", {}, a.name), h("span", {}, a.description)))));
}

// ---------- WhatsApp ----------
const WA = "whatsapp_wacli";
const waTabs = (active) => setTabs([
  [`#/${WA}`, "◉", "Status"], [`#/${WA}/contacts`, "👥", "Contatos"],
  [`#/${WA}/requests`, "✋", "Pedidos"], [`#/${WA}/unknown`, "❔", "Novos"]], active);

async function waStatus() {
  setTop("WhatsApp", true); waTabs(`#/${WA}`); loading();
  try {
    const s = await api(`${WA}/status`);
    const g = s.gate || {}, c = g.sent_today || {};
    const units = Object.entries(s.units || {}).map(([u, st]) => h("div", { class: "row" }, h("span", { class: "k" }, u), pill(st, st === "active" ? "ok" : "bad")));
    const conn = h("div", { class: "card" }, h("h2", {}, "Conexão"),
      h("div", { class: "row" }, h("span", { class: "k" }, "Sessão"), s.authenticated ? pill("conectada", "ok") : pill("desconectada", "bad")),
      s.session_revoked ? h("div", { class: "row" }, h("span", { class: "k" }, "Celular"), pill("aparelho desvinculado", "bad")) : null,
      h("div", { class: "row" }, h("span", { class: "k" }, "Última mensagem recebida"), h("span", {}, s.last_incoming || "—")),
      h("div", { class: "row" }, h("span", { class: "k" }, "Mensagens no banco"), h("span", {}, (s.store && s.store.messages) ?? "—")), ...units);
    const parts = [conn];
    if (s.gate) {
      parts.push(h("div", { class: "card" }, h("h2", {}, "Portão"),
        h("div", { class: "row" }, h("span", { class: "k" }, "Envios"), g.paused ? pill("PAUSADO", "bad") : pill("liberados", "ok")),
        g.new_contacts_paused ? h("div", { class: "row" }, h("span", { class: "k" }, "Contatos novos"), pill("pausados pelo WhatsApp", "warn")) : null,
        h("div", { class: "row" }, h("span", { class: "k" }, "Janela agora"), (g.window || [])[0] ? pill("aberta", "ok") : pill((g.window || [])[1] || "fechada", "warn")),
        h("div", { class: "row" }, h("span", { class: "k" }, "Enviados hoje"), h("span", {}, `${c.contacts ?? 0} para contatos · ${c.owner ?? 0} para você`)),
        h("div", { class: "row" }, h("span", { class: "k" }, "Contatos novos hoje"), h("span", {}, c.new_contacts ?? 0)),
        h("div", { class: "row" }, h("span", { class: "k" }, "Registro de envios"), s.log && s.log.ok ? pill(`íntegro (${s.log.events})`, "ok") : pill("adulterado!", "bad")),
        h("div", { class: "btns" }, g.paused
          ? h("button", { class: "btn primary", onclick: () => act("resume", {}, "Envios liberados") }, "Liberar envios")
          : h("button", { class: "btn danger", onclick: () => act("pause", {}, "Envios pausados") }, "Pausar tudo"))));
    }
    view.replaceChildren(...parts);
  } catch (e) { fail(e); }
}

async function act(path, body, ok) {
  try { await api(`${WA}/${path}`, body); toast(ok); route(); } catch (e) { toast(e.message); }
}

async function waContacts() {
  setTop("Contatos", true); waTabs(`#/${WA}/contacts`); loading();
  try {
    const { contacts } = await api(`${WA}/contacts`);
    const q = h("input", { placeholder: "Buscar nome ou número", oninput: () => draw() });
    const list = h("div", { class: "list" });
    const draw = () => {
      const t = q.value.toLowerCase();
      const rows = contacts.filter((c) => !t || (c.name || "").toLowerCase().includes(t) || c.num.includes(t));
      list.replaceChildren(...(rows.length ? rows.map((c) => h("div", { class: "item", onclick: () => (location.hash = `#/${WA}/chat/${c.num}`) },
        h("div", { class: "avatar" }, initials(c.name || c.num.slice(-2))),
        h("div", { class: "main" }, h("div", { class: "name" }, c.name || fmtNum(c.num)), h("div", { class: "sub" }, c.preview || fmtNum(c.num))),
        h("div", { class: "meta" }, c.blocked ? pill("bloqueado", "bad") : pill(c.role || "—"), h("div", {}, c.last)))) : [h("p", { class: "empty" }, "Ninguém na allowlist ainda.")]));
    };
    draw();
    view.replaceChildren(h("div", { class: "card" }, q, h("div", { class: "btns" },
      h("button", { class: "btn primary", onclick: () => (location.hash = `#/${WA}/add`) }, "+ Adicionar contato"))), h("div", { class: "card" }, list));
  } catch (e) { fail(e); }
}

async function waChat(num) {
  setTop(fmtNum(num), true); waTabs(`#/${WA}/contacts`); loading();
  try {
    const [chat, { contacts }] = await Promise.all([api(`${WA}/chat?num=${num}&limit=80`), api(`${WA}/contacts`)]);
    const c = contacts.find((x) => x.num === num) || { num, allowed: false, blocked: false };
    setTop(chat.name || c.name || fmtNum(num), true);
    const info = h("div", { class: "card" },
      h("div", { class: "row" }, h("span", { class: "k" }, "Número"), h("span", {}, fmtNum(num))),
      c.role ? h("div", { class: "row" }, h("span", { class: "k" }, "Papel"), pill(c.role)) : null,
      c.added ? h("div", { class: "row" }, h("span", { class: "k" }, "Na allowlist desde"), h("span", {}, c.added)) : null,
      h("div", { class: "btns" },
        c.allowed ? h("button", { class: "btn", onclick: () => confirm("Tirar da allowlist?") && act("contacts/remove", { num }, "Removido da allowlist") }, "Tirar da allowlist")
          : h("button", { class: "btn primary", onclick: () => (location.hash = `#/${WA}/add?num=${num}`) }, "Pôr na allowlist"),
        c.blocked ? h("button", { class: "btn", onclick: () => act("contacts/unblock", { num }, "Desbloqueado") }, "Desbloquear")
          : h("button", { class: "btn danger", onclick: () => confirm("Bloquear? O agente não manda mais nada para ele.") && act("contacts/block", { num }, "Bloqueado") }, "Bloquear")));
    const legend = h("div", { class: "legend" }, h("span", {}, h("i", { style: "background:var(--card2)" }), "contato"),
      h("span", {}, h("i", { style: "background:var(--agent)" }), "agente"), h("span", {}, h("i", { style: "background:var(--owner)" }), "você"));
    const bubbles = chat.messages.length ? chat.messages.map((m) => h("div", { class: "bubble " + m.who },
      m.text || (m.reaction ? m.reaction : m.media ? `[${m.media}]` : "…"), h("small", {}, m.when))) : [h("p", { class: "empty" }, "Sem mensagens guardadas.")];
    view.replaceChildren(info, h("div", { class: "card" }, legend, h("div", { class: "chat" }, bubbles)));
    window.scrollTo(0, document.body.scrollHeight);
  } catch (e) { fail(e); }
}

function waAdd(num = "") {
  setTop("Adicionar contato", true); waTabs(`#/${WA}/contacts`);
  const n = h("input", { placeholder: "Número com DDD (ex.: 11 99999-9999)", inputmode: "tel", value: num });
  const name = h("input", { placeholder: "Nome" });
  const app = HUB.apps.find((a) => a.id === WA) || {};
  const role = h("select", {}, ...(app.roles || []).map(([v, label]) => h("option", { value: v }, label)));
  const lead = h("input", { placeholder: "Lead ou assunto (opcional)" });
  view.replaceChildren(h("div", { class: "card" }, h("h2", {}, "O agente poderá responder esta pessoa sem pedir seu OK."), n, name, role, lead,
    h("div", { class: "btns" }, h("button", { class: "btn primary", onclick: async () => {
      try { await api(`${WA}/contacts/add`, { num: n.value, name: name.value, role: role.value, lead: lead.value }); toast("Adicionado"); location.hash = `#/${WA}/contacts`; }
      catch (e) { toast(e.message); } } }, "Adicionar"))));
}

async function waRequests() {
  setTop("Pedidos de envio", true); waTabs(`#/${WA}/requests`); loading();
  try {
    const { requests } = await api(`${WA}/requests`);
    const stateLabel = { pending: ["esperando você", "warn"], approved: ["aprovado, na fila", "ok"], sent: ["enviado", "ok"], rejected: ["descartado", ""],
      cancelled: ["cancelado", ""], expired: ["vencido", ""], unknown: ["incerto", "bad"], sending: ["enviando", "warn"] };
    view.replaceChildren(...(requests.length ? requests.map((r) => {
      const [lbl, kind] = stateLabel[r.state] || [r.state, ""];
      return h("div", { class: "card" },
        h("div", { class: "row" }, h("b", {}, r.name || fmtNum(r.to)), pill(lbl, kind)),
        h("div", { class: "sub", style: "color:var(--muted);font-size:13px" }, `${r.code} · ${(r.created || "").slice(0, 16).replace("T", " ")} · ${r.why || ""}`),
        h("div", { class: "req-text" }, r.text || ""),
        r.state === "pending" ? h("div", { class: "btns" },
          h("button", { class: "btn primary", onclick: () => act("requests/approve", { code: r.code }, "Aprovado: sai em segundos") }, "Aprovar"),
          h("button", { class: "btn danger", onclick: () => act("requests/reject", { code: r.code }, "Descartado") }, "Descartar")) : null);
    }) : [h("p", { class: "empty" }, "Nenhum pedido.")]));
  } catch (e) { fail(e); }
}

async function waUnknown() {
  setTop("Quem escreveu e não está na lista", true); waTabs(`#/${WA}/unknown`); loading();
  try {
    const { unknown } = await api(`${WA}/unknown`);
    view.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Últimos 7 dias. O agente não responde essas pessoas."),
      h("div", { class: "list" }, ...(unknown.length ? unknown.map((u) => h("div", { class: "item", onclick: () => (location.hash = `#/${WA}/chat/${u.num}`) },
        h("div", { class: "avatar" }, initials(u.name || u.num.slice(-2))),
        h("div", { class: "main" }, h("div", { class: "name" }, u.name || fmtNum(u.num)), h("div", { class: "sub" }, `${u.count} mensagem(ns)`)),
        h("div", { class: "meta" }, u.last))) : [h("p", { class: "empty" }, "Ninguém novo.")]))));
  } catch (e) { fail(e); }
}

// ---------- rotas ----------
function route() {
  const [path, query] = (location.hash || "#/").slice(1).split("?");
  const p = path.split("/").filter(Boolean);
  const qs = new URLSearchParams(query || "");
  if (!p.length) return home();
  if (p[0] === WA) {
    if (!p[1]) return waStatus();
    if (p[1] === "contacts") return waContacts();
    if (p[1] === "chat") return waChat(p[2]);
    if (p[1] === "add") return waAdd(qs.get("num") || "");
    if (p[1] === "requests") return waRequests();
    if (p[1] === "unknown") return waUnknown();
  }
  home();
}
back.onclick = () => (history.length > 1 ? history.back() : (location.hash = "#/"));
$("#refresh").onclick = () => route();
window.addEventListener("hashchange", route);
document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && route());
(async () => {
  try { HUB = await api("apps"); } catch (e) { view.replaceChildren(h("p", { class: "empty" }, "Sem acesso: " + e.message)); return; }
  route();
})();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
