/* Observatório RJ/RE – front-end (portal público com cadastro + área restrita).
   Camadas: núcleo (DOM seguro, API, formatação) → componentes (tema Plotly, cartões, KPIs, tabelas, portão de cadastro)
   → páginas (rotas por hash). Nada é inserido via innerHTML; o código administrativo (mnt.js) só chega ao mantenedor.
   O cadastro é exigido pelo SERVIDOR: sem ele, as rotas devolvem só a prévia; aqui apenas se exibe o formulário. */
"use strict";
(() => {
  // =============================================================== núcleo
  const E = {csrf: null, usuario: null, recursos: [], views: {}, atual: null, cache: {}, liberado: false, exigido: true, visitante: null, modalMostrado: false};
  const $ = (s) => document.querySelector(s);
  const SVG = "http://www.w3.org/2000/svg";

  function el(tag, at, ...filhos) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(at || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "on") for (const [ev, fn] of Object.entries(v)) n.addEventListener(ev, fn);
      else if (k === "class") n.className = v;
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const f of filhos.flat(Infinity)) if (f !== null && f !== undefined && f !== false) n.append(f instanceof Node ? f : document.createTextNode(String(f)));
    return n;
  }

  async function api(caminho, opt = {}) {
    const o = {method: opt.method || "GET", headers: {}, credentials: "same-origin"};
    if (opt.corpo !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opt.corpo); }
    if (opt.bytes) { o.headers["Content-Type"] = "application/octet-stream"; o.body = opt.bytes; }
    if (o.method !== "GET" && E.csrf) o.headers["X-CSRF"] = E.csrf;
    let r;
    try { r = await fetch(caminho, o); } catch (e) { throw new Error("Sem conexão com o servidor."); }
    if (r.status === 401) { sairLocal(); throw new Error("Sua sessão expirou. Entre novamente pela Área restrita."); }
    const d = (r.headers.get("Content-Type") || "").includes("json") ? await r.json() : null;
    if (!r.ok) throw new Error((d && d.erro ? d.erro : "Não foi possível concluir.") + (d && d.codigo ? ` (código ${d.codigo})` : ""));
    return d;
  }
  const publico = async (s) => (E.cache[s] ||= await api("/api/v1/publico/" + s));

  const nf = (c) => new Intl.NumberFormat("pt-BR", {minimumFractionDigits: c, maximumFractionDigits: c});
  const fmt = {
    n: (v, c = 0) => v === null || v === undefined || v === "" || Number.isNaN(+v) ? "–" : nf(c).format(v),
    p: (v, c = 1) => v === null || v === undefined ? "–" : nf(c).format(v) + "%",
    rs: (v) => v === null || v === undefined ? "–" : Math.abs(v) >= 1e9 ? "R$ " + nf(2).format(v / 1e9) + " bi" : Math.abs(v) >= 1e6 ? "R$ " + nf(1).format(v / 1e6) + " mi" : Math.abs(v) >= 1e3 ? "R$ " + nf(0).format(v / 1e3) + " mil" : "R$ " + nf(0).format(v),
    d: (t) => t ? new Date(t * 1000).toLocaleString("pt-BR") : "–",
    data: (s) => s ? s.slice(8, 10) + "/" + s.slice(5, 7) + "/" + s.slice(0, 4) : "–",
    mes: (m) => { if (!m) return "–"; const [a, b] = m.split("-"); return ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"][+b - 1] + "/" + a; },
    cnj: (n) => n && n.length === 20 ? `${n.slice(0, 7)}-${n.slice(7, 9)}.${n.slice(9, 13)}.${n.slice(13, 14)}.${n.slice(14, 16)}.${n.slice(16)}` : (n || "–"),
  };
  const ROT = {selic_meta: "Selic meta", juros_pj_livres: "Juros PJ (recursos livres)", spread_pj_livres: "Spread PJ", inadimpl_pj_total: "Inadimplência PJ",
    concessoes_pj_livres_var12m: "Concessões de crédito PJ (var. 12m)", saldo_credito_pj_var12m: "Saldo de crédito PJ (var. 12m)", cambio_usd_var12m: "Câmbio R$/US$ (var. 12m)",
    ibc_br_dessaz_var12m: "Atividade – IBC-Br (var. 12m)", desemprego_pnad: "Desemprego", ipca_12m: "IPCA 12 meses", juro_real_ex_post: "Juro real ex-post",
    pre_curto: "Juro prefixado 1,5 ano", pre_longo: "Juro prefixado 6 anos", juro_real_5a: "Juro real 5 anos", inclinacao_pre: "Inclinação da curva", constante: "Constante", "tendência (ano)": "Tendência (ano)"};
  const rotulo = (v) => { const m = /^(.*) \(defasagem (\d+)m\)$/.exec(v || ""); return m ? `${ROT[m[1]] || m[1]} – ${m[2]}m antes` : (ROT[v] || v); };
  const pv = (p) => p === null || p === undefined ? "n/d" : p < 0.001 ? "p<0,001" : "p=" + fmt.n(p, 3);
  const TIPO = {RJ: "Recuperação judicial", RE: "Recuperação extrajudicial", FAL: "Falência", "Não identificado": "Não identificado"};

  // =============================================================== componentes
  const COR = {navy: "#0F2A44", azul: "#1F5A96", ambar: "#E8A33D", teal: "#2A9D8F", verm: "#C8553D", roxo: "#7A5C99", cinza: "#5C6B7A", verde: "#4E8A3E", grade: "#E9EDF2", texto: "#1C2733", texto2: "#5C6B7A"};
  const PAL = [COR.azul, COR.ambar, COR.teal, COR.verm, COR.roxo, COR.cinza, COR.verde];
  const TEMA = {
    font: {family: "Segoe UI, system-ui, Roboto, Arial", size: 12, color: COR.texto}, separators: ",.", colorway: PAL,
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", margin: {l: 8, r: 12, t: 10, b: 8, pad: 4}, autosize: true,
    hoverlabel: {bgcolor: "#fff", bordercolor: COR.grade, font: {color: COR.texto, size: 12}},
    legend: {orientation: "h", x: 0, y: 1.08, xanchor: "left", yanchor: "bottom", font: {size: 11, color: COR.texto2}, bgcolor: "rgba(0,0,0,0)"},
    xaxis: {automargin: true, gridcolor: COR.grade, linecolor: "#C9D2DC", zeroline: false, tickfont: {color: COR.texto2}, ticks: "outside", tickcolor: "#C9D2DC", ticklen: 4},
    yaxis: {automargin: true, gridcolor: COR.grade, zeroline: false, tickfont: {color: COR.texto2}, rangemode: "tozero"},
  };
  const mescla = (a, b) => { const o = {...a}; for (const [k, v] of Object.entries(b || {})) o[k] = v && typeof v === "object" && !Array.isArray(v) && a[k] && typeof a[k] === "object" ? mescla(a[k], v) : v; return o; };

  function grafico(traces, layout = {}, proporcao = "r-media") {
    const d = el("div", {class: "graf " + proporcao, role: "img"});
    const desenhar = () => {
      if (!window.Plotly || !d.isConnected) return setTimeout(desenhar, 120);
      window.Plotly.newPlot(d, traces, mescla(TEMA, layout), {displaylogo: false, responsive: true, locale: "pt-BR",
        modeBarButtonsToRemove: ["sendDataToCloud", "lasso2d", "select2d", "autoScale2d", "toggleSpikelines", "hoverClosestCartesian", "hoverCompareCartesian"],
        toImageButtonOptions: {format: "png", scale: 2, filename: "observatorio_rj"}});
    };
    requestAnimationFrame(desenhar);
    return d;
  }

  function sparkline(valores, cor = COR.azul) {
    const v = (valores || []).filter((x) => x !== null && x !== undefined);
    const s = document.createElementNS(SVG, "svg"); s.setAttribute("class", "spark"); s.setAttribute("viewBox", "0 0 96 32"); s.setAttribute("aria-hidden", "true");
    if (v.length < 2) return s;
    const mn = Math.min(...v), mx = Math.max(...v), r = mx - mn || 1;
    const pts = v.map((y, i) => [i / (v.length - 1) * 94 + 1, 30 - (y - mn) / r * 26]);
    const area = document.createElementNS(SVG, "path"); area.setAttribute("d", "M" + pts.map((p) => p.join(",")).join("L") + "L95,31L1,31Z"); area.setAttribute("fill", cor); area.setAttribute("opacity", ".10");
    const linha = document.createElementNS(SVG, "polyline"); linha.setAttribute("points", pts.map((p) => p.join(",")).join(" ")); linha.setAttribute("fill", "none"); linha.setAttribute("stroke", cor); linha.setAttribute("stroke-width", "1.6");
    const c = document.createElementNS(SVG, "circle"); const u = pts[pts.length - 1]; c.setAttribute("cx", u[0]); c.setAttribute("cy", u[1]); c.setAttribute("r", "2.4"); c.setAttribute("fill", cor);
    s.append(area, linha, c); return s;
  }

  const kpi = (v, r, n, extra) => el("div", {class: "kpi"}, el("div", {class: "r"}, r), el("div", {class: "v"}, v), el("div", {class: "n"}, n || ""), extra || null);
  function cartao(titulo, corpo, fonte, o = {}) {
    return el("section", {class: "cartao " + (o.span || "s6")}, el("h3", {}, titulo), o.sub ? el("p", {class: "sub"}, o.sub) : null, el("div", {class: "corpo"}, corpo), fonte ? el("div", {class: "fonte"}, "Fonte: " + fonte) : null);
  }
  const titulo = (t, s, acoes) => [el("div", {class: "cab"}, el("div", {}, el("h1", {}, t), s ? el("p", {}, s) : null), acoes ? el("div", {class: "acoes"}, acoes) : null)];
  const vazio = (t) => el("div", {class: "aviso"}, t);
  const preparando = () => el("div", {class: "info"}, "Os dados desta seção ainda não foram gerados. Eles aparecem aqui após a próxima execução da rotina de coleta e processamento.");

  function tabela(linhas, colunas, max = 200) {
    if (!linhas || !linhas.length) return el("p", {class: "vazio"}, "Sem dados.");
    const cols = colunas || Object.keys(linhas[0]).map((k) => [k, k]);
    const ehNum = (c) => !c[2] && linhas.slice(0, 20).every((l) => { const v = l[c[0]]; return v === null || v === undefined || typeof v === "number"; });
    const nums = cols.map((c) => ehNum(c) || c[3] === "n");
    return el("div", {class: "tabela"}, el("table", {}, el("thead", {}, el("tr", {}, cols.map((c, i) => el("th", {class: nums[i] ? "n" : null, scope: "col"}, c[1])))),
      el("tbody", {}, linhas.slice(0, max).map((l) => el("tr", {}, cols.map((c, i) => {
        const v = typeof c[2] === "function" ? c[2](l[c[0]], l) : l[c[0]];
        return el("td", {class: nums[i] ? "n" : (c[3] || null)}, v instanceof Node ? v : v === null || v === undefined ? "" : typeof v === "number" ? fmt.n(v, Number.isInteger(v) ? 0 : 2) : String(v));
      }))))));
  }
  const grade = (...c) => el("div", {class: "grade"}, c);

  // =============================================================== cadastro de interessados
  let PRIV = null;
  async function formCadastro(aoConcluir) {
    PRIV ||= await publico("privacidade");
    const m = el("p", {class: "msg", role: "alert"});
    const f = el("form", {class: "cad-form"},
      el("div", {class: "linha2"}, el("label", {}, "Nome", el("input", {name: "nome", required: true, maxlength: 120, autocomplete: "name"})),
        el("label", {}, "E-mail", el("input", {name: "email", type: "email", required: true, maxlength: 200, autocomplete: "email"}))),
      el("div", {class: "linha2"}, el("label", {}, "Organização (opcional)", el("input", {name: "organizacao", maxlength: 160, autocomplete: "organization"})),
        el("label", {}, "Perfil", el("select", {name: "perfil", required: true}, el("option", {value: ""}, "Selecione"), PRIV.perfis.map((p) => el("option", {}, p))))),
      el("label", {}, "Qual seu interesse no tema? (opcional)", el("input", {name: "interesse", maxlength: 500})),
      el("input", {name: "site", class: "isca", tabindex: "-1", autocomplete: "off", "aria-hidden": "true"}),
      el("label", {class: "check"}, el("input", {type: "checkbox", name: "consentimento", required: true}), el("span", {class: "legal"}, PRIV.consentimento, " ", el("a", {href: "#privacidade"}, "Política de privacidade"), ".")),
      el("label", {class: "check"}, el("input", {type: "checkbox", name: "novidades"}), el("span", {class: "legal"}, "Quero receber avisos quando houver atualização dos dados (opcional).")),
      el("div", {}, el("button", {class: "btn btn-destaque", type: "submit"}, "Liberar acesso completo")), m);
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault(); m.className = "msg"; m.textContent = "";
      const o = Object.fromEntries(new FormData(f)); o.consentimento = !!f.consentimento.checked; o.novidades = !!f.novidades.checked;
      try {
        const r = await api("/api/v1/publico/cadastro", {method: "POST", corpo: o});
        E.liberado = true; E.visitante = r.nome; E.cache = {}; atualizarTopo(); montarMenu();
        m.className = "msg ok"; m.textContent = "Acesso liberado. Obrigado!";
        if (aoConcluir) aoConcluir();
      } catch (e) { m.textContent = e.message; }
    });
    return f;
  }

  async function portao(texto) {
    const fantasmas = el("div", {class: "fantasmas", "aria-hidden": "true"}, el("div"), el("div"), el("div"), el("div"));
    const caixa = el("div", {class: "chamada"}, el("h2", {}, "Continue com acesso completo"),
      el("p", {}, texto || "Faça um cadastro rápido e gratuito para ver todos os gráficos, tabelas de processos e partes, estatísticas e previsões."),
      await formCadastro(() => rotear()));
    return el("div", {class: "portao", id: "portao"}, fantasmas, caixa);
  }

  async function abrirModalCadastro() {
    if (E.liberado || E.modalMostrado || !E.exigido) return;
    E.modalMostrado = true;
    const d = $("#dlg-cadastro"); const corpo = $("#cadastro-corpo");
    corpo.replaceChildren(el("h2", {}, "Para continuar, faça seu cadastro"),
      el("p", {class: "sub"}, "O conteúdo completo do Observatório é gratuito para quem se cadastra. Leva menos de um minuto."),
      await formCadastro(() => { d.close(); rotear(); }),
      el("div", {class: "acoes"}, el("button", {class: "btn btn-sec", type: "button", on: {click: () => d.close()}}, "Agora não")));
    d.showModal();
  }

  /** Observa o fim da prévia: ao rolar até ele, abre o cadastro (uma vez por visita). */
  function sentinela() {
    const s = el("div", {style: "height:1px"});
    requestAnimationFrame(() => {
      if (!("IntersectionObserver" in window)) return;
      const io = new IntersectionObserver((es) => { if (es.some((x) => x.isIntersecting)) { io.disconnect(); abrirModalCadastro(); } }, {rootMargin: "0px 0px -20% 0px"});
      io.observe(s);
    });
    return s;
  }

  // =============================================================== navegação
  const ICONES = {visao: "M3 13h4v8H3zM10 8h4v13h-4zM17 3h4v18h-4z", processos: "M4 4h10l6 6v10H4zM14 4v6h6M8 13h8M8 17h6", tendencia: "M3 17l6-6 4 4 8-8M15 7h6v6", macro: "M4 19V5M4 19h16M8 15l3-4 3 2 5-6",
    credores: "M12 3l9 4-9 4-9-4 9-4zM3 12l9 4 9-4M3 17l9 4 9-4", metodologia: "M5 4h11l3 3v13H5zM9 9h6M9 13h6M9 17h4", privacidade: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
    contato: "M4 6h16v12H4zM4 7l8 6 8-6", carteira: "M3 7h18v13H3zM8 7V4h8v3", psi: "M9 11l3 3 7-7M20 12v7H4V5h11", conta: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0",
    suporte: "M4 12a8 8 0 1116 0v5h-4v-6h4M4 11v6h4v-6H4", resumo: "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z",
    interessados: "M9 11a3 3 0 100-6 3 3 0 000 6zM3 20a6 6 0 0112 0M17 8v6M14 11h6", usuarios: "M9 11a3 3 0 100-6 3 3 0 000 6zM3 20a6 6 0 0112 0M16 11a3 3 0 100-6M21 20a6 6 0 00-4-5.6",
    assinaturas: "M4 6h16v12H4zM4 10h16M8 15h3", auditoria: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M9 12l2 2 4-4", sac: "M4 5h16v11H8l-4 4z",
    rede: "M12 3a9 9 0 100 18 9 9 0 000-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"};
  function icone(id) {
    const s = document.createElementNS(SVG, "svg"); s.setAttribute("class", "ic"); s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true");
    const p = document.createElementNS(SVG, "path"); p.setAttribute("d", ICONES[id] || "M5 12h14"); p.setAttribute("fill", "none"); p.setAttribute("stroke", "currentColor"); p.setAttribute("stroke-width", "1.8"); p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round");
    s.append(p); return s;
  }

  function registrar(id, rotulo_, grupo, recurso, fn, cadastro) { E.views[id] = {rotulo: rotulo_, grupo, recurso, fn, cadastro}; }
  const visivel = (v) => v.recurso === "publico" || (E.usuario && (!v.recurso || E.recursos.includes(v.recurso)));

  function montarMenu() {
    const nav = $("#menu"); nav.replaceChildren(); let g = null;
    for (const [id, v] of Object.entries(E.views)) {
      if (!visivel(v)) continue;
      if (v.grupo !== g) { g = v.grupo; nav.append(el("div", {class: "grupo"}, g)); }
      nav.append(el("a", {href: "#" + id, "data-id": id, class: id === E.atual ? "ativo" : null}, icone(id.replace("mnt-", "")), v.rotulo,
        v.cadastro && !E.liberado && E.exigido ? el("span", {class: "cad", title: "Prévia – conteúdo completo após cadastro"}, "prévia") : null));
    }
  }

  async function abrir(id) {
    const v = E.views[id] && visivel(E.views[id]) ? E.views[id] : E.views.visao;
    id = Object.keys(E.views).find((k) => E.views[k] === v); E.atual = id;
    document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("ativo", a.dataset.id === id));
    const c = $("#conteudo"); c.replaceChildren(el("div", {class: "esqueleto"}));
    try { c.replaceChildren(...[await v.fn()].flat(Infinity).filter((x) => x !== null && x !== undefined)); }
    catch (e) { c.replaceChildren(vazio(e.message)); }
    document.title = v.rotulo + " · Observatório RJ/RE"; c.focus({preventScroll: true}); window.scrollTo({top: 0});
  }
  const rotear = () => abrir((location.hash || "#visao").slice(1));

  // =============================================================== sessão
  function atualizarTopo() {
    const n = $("#nome-usuario");
    if (E.usuario) { n.textContent = E.usuario.nome; n.hidden = false; }
    else if (E.visitante) { n.textContent = "Olá, " + E.visitante; n.hidden = false; }
    else n.hidden = true;
    $("#btn-cadastro").hidden = E.liberado || !E.exigido;
    $("#btn-entrar").hidden = !!E.usuario; $("#btn-sair").hidden = !E.usuario;
  }
  function sairLocal() { E.csrf = null; E.usuario = null; E.recursos = []; E.liberado = !!E.visitante || !E.exigido; atualizarTopo(); montarMenu(); }
  function aplicarSessao(s) {
    E.exigido = s.cadastro_exigido !== false; E.liberado = !!s.liberado; E.visitante = s.visitante || null;
    if (s.autenticado) {
      E.csrf = s.csrf; E.usuario = s.usuario; E.recursos = s.recursos || []; E.liberado = true;
      if (s.usuario.papel === "mantenedor" && !document.getElementById("js-mnt")) {
        const sc = el("script", {src: "/static/mnt.js", id: "js-mnt"}); sc.addEventListener("load", montarMenu); document.body.append(sc);
      }
    }
    atualizarTopo(); montarMenu();
  }

  async function entrar(ev) {
    ev.preventDefault();
    const f = ev.target, m = $("#msg-login"); m.textContent = ""; m.className = "msg";
    try {
      const r = await api("/api/v1/entrar", {method: "POST", corpo: Object.fromEntries(new FormData(f))});
      if (r.precisa_2fa) { $("#bloco-2fa").hidden = false; m.className = "msg ok"; m.textContent = "Informe o código do aplicativo autenticador."; f.codigo.focus(); return; }
      f.reset(); $("#bloco-2fa").hidden = true; $("#dlg-login").close(); E.cache = {};
      aplicarSessao(Object.assign({autenticado: true, liberado: true, cadastro_exigido: E.exigido, visitante: E.visitante}, r));
      location.hash = r.usuario.trocar_senha ? "#conta" : (E.recursos.includes("carteira") ? "#carteira" : "#visao"); rotear();
    } catch (e) { m.textContent = e.message; }
  }

  async function iniciar() {
    registrarPaginas();
    $("#btn-entrar").addEventListener("click", () => $("#dlg-login").showModal());
    $("#btn-cadastro").addEventListener("click", () => { E.modalMostrado = false; abrirModalCadastro(); });
    $("#fechar-login").addEventListener("click", () => $("#dlg-login").close());
    $("#form-login").addEventListener("submit", entrar);
    $("#usar-recuperacao").addEventListener("click", () => { $("#bloco-recup").hidden = false; });
    $("#btn-sair").addEventListener("click", async () => { try { await api("/api/v1/sair", {method: "POST"}); } catch (e) {} E.cache = {}; sairLocal(); location.hash = "#visao"; rotear(); });
    window.addEventListener("hashchange", rotear);
    try { aplicarSessao(await api("/api/v1/sessao")); } catch (e) {}
    montarMenu(); rotear();
    publico("resumo").then((r) => { if (r.atualizado) { const s = $("#selo-atualizacao"); s.textContent = "Atualizado em " + r.atualizado; s.hidden = false; } }).catch(() => {});
  }

  // =============================================================== gráficos de domínio
  function regimesShapes(regimes) {
    if (!regimes || regimes.length < 2) return {shapes: [], annotations: []};
    const cores = ["rgba(31,90,150,.05)", "rgba(232,163,61,.08)"];
    return {shapes: regimes.map((r, i) => ({type: "rect", xref: "x", yref: "paper", x0: r.de, x1: r.ate, y0: 0, y1: 1, fillcolor: cores[i % 2], line: {width: 0}, layer: "below"})),
      annotations: regimes.map((r) => ({xref: "x", yref: "paper", x: r.de, y: 1, xanchor: "left", yanchor: "top", showarrow: false, text: "média " + fmt.n(r.media, 0), font: {size: 10, color: COR.texto2}}))};
  }

  function graficoPrevisao(t) {
    const x = t.meses, fx = t.previsao_meses || [], ens = t.previsao_ensemble || [];
    const ultX = x[x.length - 1], ultY = t.observado[t.observado.length - 1];
    const reg = regimesShapes(t.regimes);
    const tr = [
      {type: "bar", name: "Pedidos de RJ no mês", x, y: t.observado, marker: {color: "rgba(31,90,150,.28)"}, hovertemplate: "%{y:,.0f}<extra>observado</extra>"},
      t.tendencia ? {type: "scatter", mode: "lines", name: "Tendência", x, y: t.tendencia, line: {color: COR.azul, width: 2.6}, hovertemplate: "%{y:,.0f}<extra>tendência</extra>"} : null,
      ens.length ? {type: "scatter", mode: "lines", x: [ultX, ...fx], y: [ultY, ...ens.map((p) => p.sup)], line: {width: 0}, showlegend: false, hoverinfo: "skip"} : null,
      ens.length ? {type: "scatter", mode: "lines", name: "Intervalo de 80%", x: [ultX, ...fx], y: [ultY, ...ens.map((p) => p.inf)], fill: "tonexty", fillcolor: "rgba(232,163,61,.22)", line: {width: 0}, hovertemplate: "%{y:,.0f}<extra>limite</extra>"} : null,
      ens.length ? {type: "scatter", mode: "lines+markers", name: "Previsão (ensemble)", x: [ultX, ...fx], y: [ultY, ...ens.map((p) => p.previsto)], line: {color: COR.ambar, width: 2.6, dash: "dot"}, marker: {size: 4}, hovertemplate: "%{y:,.0f}<extra>previsão</extra>"} : null,
    ].filter(Boolean);
    return grafico(tr, {hovermode: "x unified", bargap: 0.15, shapes: reg.shapes, annotations: reg.annotations,
      xaxis: {type: "date", tickformat: "%Y", hoverformat: "%m/%Y", rangeslider: {visible: true, thickness: 0.06, bgcolor: "#F5F7FA"}},
      yaxis: {title: {text: "processos/mês", font: {size: 11, color: COR.texto2}}}}, "r-larga");
  }

  function leituraRapida(r, t) {
    const frases = [];
    if (r["variacao_12m_%"] !== null && r["variacao_12m_%"] !== undefined)
      frases.push(`Nos últimos 12 meses foram ${fmt.n(r.acumulado_12m)} pedidos de recuperação judicial, ${r["variacao_12m_%"] >= 0 ? "alta" : "queda"} de ${fmt.p(Math.abs(r["variacao_12m_%"]))} sobre os 12 meses anteriores.`);
    if (r.proximos_12m) frases.push(`O ensemble de modelos projeta cerca de ${fmt.n(r.proximos_12m)} pedidos nos próximos 12 meses.`);
    if (t && t.indices_sazonais) {
      const nomes = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
      const mx = t.indices_sazonais.indexOf(Math.max(...t.indices_sazonais)), mn = t.indices_sazonais.indexOf(Math.min(...t.indices_sazonais));
      frases.push(`Há sazonalidade: ${nomes[mx]} costuma ficar ${fmt.p((t.indices_sazonais[mx] - 1) * 100, 0)} acima da tendência e ${nomes[mn]}, ${fmt.p((1 - t.indices_sazonais[mn]) * 100, 0)} abaixo.`);
    }
    if (t && t.regimes && t.regimes.length > 1) { const u = t.regimes[t.regimes.length - 1]; frases.push(`O teste de mudança de regime identifica ${t.regimes.length} fases; a atual começou em ${fmt.mes(u.de)}, com média de ${fmt.n(u.media)} pedidos/mês.`); }
    if (r.processos_identificados) frases.push(`O cruzamento das publicações do DJEN com o DataJud identificou ${fmt.n(r.processos_identificados)} processos com partes, credores ou marcos processuais.`);
    if (r.hhi_bancos) frases.push(`A concentração dos créditos bancários listados nos editais é ${r.hhi_bancos < 1500 ? "baixa" : r.hhi_bancos <= 2500 ? "moderada" : "alta"} (HHI ${fmt.n(r.hhi_bancos)}).`);
    return frases.length ? el("div", {}, frases.map((f) => el("p", {style: "margin:0 0 8px"}, f))) : el("p", {class: "vazio"}, "Leitura indisponível.");
  }

  // =============================================================== páginas
  function registrarPaginas() {
    const G = "Portal";

    registrar("visao", "Visão geral", G, "publico", async () => {
      const r = await publico("resumo"); const t = r.grafico || {};
      const cab = titulo("Recuperação judicial e extrajudicial no Brasil", "Panorama construído a partir de dados públicos do Judiciário, do Banco Central e do Tesouro, com cruzamento de processos e partes, estatísticas e previsões atualizadas a cada coleta.");
      if (!t.meses) return [...cab, preparando()];
      const v = r["variacao_12m_%"];
      const topo = [...cab,
        el("div", {class: "kpis"},
          kpi(fmt.n(r.acumulado_12m), "Pedidos de RJ – últimos 12 meses", el("span", {}, el("span", {class: "d " + (v >= 0 ? "sobe" : "desce")}, (v >= 0 ? "▲ " : "▼ ") + fmt.p(Math.abs(v))), " vs. 12 meses anteriores"), sparkline(r.serie_12m)),
          kpi(fmt.n(r.proximos_12m), "Projeção – próximos 12 meses", "ensemble de modelos validados", sparkline((t.previsao_ensemble || []).map((p) => p.previsto), COR.ambar)),
          kpi(fmt.n(r.processos_identificados), "Processos identificados", "cruzamento DJEN × DataJud × editais"),
          kpi(r.passivo_listado ? fmt.rs(r.passivo_listado) : "–", "Passivo listado em editais", fmt.n(r.processos_credores) + " processos com lista extraída")),
        grade(cartao("Pedidos de recuperação judicial: histórico, tendência e previsão", graficoPrevisao(t), "CNJ DataJud; modelos do Observatório", {span: "s12", sub: "Barras: pedidos mensais · linha: tendência · faixa: previsão com intervalo de 80% · áreas sombreadas: regimes estatísticos"}),
          cartao("Leitura rápida", leituraRapida(r, t), null, {span: "s12"}))];
      const d = await publico("tendencia");
      if (d.previa) return [...topo, sentinela(), await portao("Continue lendo: distribuição por UF, varas, processos ajuizados por ano e todas as demais seções do Observatório ficam disponíveis após um cadastro rápido e gratuito.")];
      const anos = [...new Set((d.anual || []).map((a) => a.ano))];
      const tipos = [["RJ", "Recuperação judicial", COR.azul], ["FAL", "Falência", COR.cinza], ["RE", "Recuperação extrajudicial", COR.ambar]];
      const uf = (d.uf || []).slice(0, 15).reverse();
      return [...topo, el("div", {style: "height:16px"}), grade(
        cartao("Processos ajuizados por ano", grafico(tipos.map(([k, n, c]) => ({type: "bar", name: n, x: anos, y: anos.map((a) => (d.anual.find((z) => z.ano === a && z.tipo === k) || {}).qtd || 0), marker: {color: c}, hovertemplate: "%{y:,.0f}<extra>" + n + "</extra>"})),
          {barmode: "group", bargap: 0.25, bargroupgap: 0.05, hovermode: "x unified", xaxis: {type: "category"}}, "r-media"), "CNJ DataJud", {span: "s12"}),
        cartao("Recuperações judiciais por UF", grafico([{type: "bar", orientation: "h", y: uf.map((u) => u.uf), x: uf.map((u) => u.qtd), marker: {color: uf.map((_, i) => i >= uf.length - 3 ? COR.azul : "rgba(31,90,150,.45)")},
          text: uf.map((u) => fmt.n(u.qtd)), textposition: "outside", cliponaxis: false, hovertemplate: "%{y}: %{x:,.0f}<extra></extra>"}], {xaxis: {showgrid: false, showticklabels: false}, yaxis: {type: "category"}, margin: {r: 40}}, "r-quadrada"), "CNJ DataJud – 15 UFs com mais processos", {span: "s6"}),
        cartao("Varas com mais recuperações judiciais", tabela(d.varas, [["orgao", "Órgão julgador", null, "quebra"], ["tribunal", "Tribunal"], ["qtd", "Processos"]], 15), "CNJ DataJud", {span: "s6"}))];
    });

    registrar("processos", "Processos e partes", G, "publico", async () => {
      const d = await publico("processos");
      const cab = titulo("Processos, partes e grupos", "Resultado do cruzamento entre as publicações do DJEN, os editais de credores, a consulta processo a processo no DataJud e o cadastro da CVM.");
      if (!d.total) return [...cab, preparando()];
      const porTipo = cartao("Processos identificados por tipo", grafico([{type: "bar", x: d.por_tipo.map((x) => TIPO[x.categoria] || x.categoria), y: d.por_tipo.map((x) => x.processos),
        marker: {color: d.por_tipo.map((x) => ({RJ: COR.azul, RE: COR.ambar, FAL: COR.cinza}[x.categoria] || "#C9D2DC"))}, text: d.por_tipo.map((x) => fmt.n(x.processos)), textposition: "outside", cliponaxis: false,
        hovertemplate: "%{x}: %{y}<extra></extra>"}], {xaxis: {type: "category"}}, "r-media"), "Classe no DataJud; na falta, classe informada no DJEN ou tipo do edital", {span: d.previa ? "s12" : "s5"});
      const k = el("div", {class: "kpis"}, kpi(fmt.n(d.total), "Processos identificados", "a partir das publicações do DJEN"),
        kpi(fmt.n(d.com_datajud), "Com ficha no DataJud", "classe, ajuizamento, órgão e movimentos"), kpi(fmt.n(d.com_edital), "Com edital de credores", "credores, classes e valores"));
      if (d.previa) return [...cab, k, grade(porTipo), sentinela(), await portao("A lista de processos com partes, credores, tempos processuais, grupos econômicos e companhias abertas fica disponível após o cadastro.")];
      const td = d.tempo_deferimento || {}, cv = d.convolacao || {}, li = d.litisconsorcio || {};
      k.append(kpi(td.mediana !== null && td.mediana !== undefined ? fmt.n(td.mediana) + " dias" : "–", "Mediana até o deferimento", fmt.n(td.n) + " processos com as duas datas"),
        kpi(li.processos_com_devedora ? fmt.p(li.mais_de_uma_empresa / li.processos_com_devedora * 100) : "–", "Pedidos com mais de uma empresa", "litisconsórcio entre devedoras (edital)"));
      const trib = [...(d.por_tribunal || [])].reverse();
      const cards = [porTipo,
        cartao("Processos por tribunal", grafico([{type: "bar", orientation: "h", y: trib.map((x) => x.categoria), x: trib.map((x) => x.processos), marker: {color: COR.azul}, text: trib.map((x) => fmt.n(x.processos)), textposition: "outside", cliponaxis: false}],
          {xaxis: {showticklabels: false, showgrid: false}, yaxis: {type: "category"}, margin: {r: 36}}, "r-media"), "DJEN / DataJud", {span: "s7"})];
      if ((td.por_uf || []).length) cards.push(cartao("Dias até o deferimento do processamento (mediana por UF)", grafico([{type: "bar", x: td.por_uf.map((x) => x.uf), y: td.por_uf.map((x) => x.mediana_dias), marker: {color: COR.teal},
        customdata: td.por_uf.map((x) => x.processos), text: td.por_uf.map((x) => fmt.n(x.mediana_dias)), textposition: "outside", cliponaxis: false, hovertemplate: "%{x}: %{y:.0f} dias (%{customdata} processos)<extra></extra>"}], {xaxis: {type: "category"}}, "r-media"),
        "DataJud – movimentos com 'defer' no nome; UFs com ao menos 5 processos", {span: "s7"}));
      if (td.especializada && (td.especializada.n || td.comum.n)) cards.push(cartao("Vara especializada × vara comum", el("div", {},
        grafico([{type: "bar", x: ["Especializada", "Comum"], y: [td.especializada.mediana, td.comum.mediana], marker: {color: [COR.azul, COR.cinza]}, text: [td.especializada.mediana, td.comum.mediana].map((x) => x === null ? "–" : fmt.n(x) + " dias"), textposition: "outside", cliponaxis: false}],
          {xaxis: {type: "category"}, yaxis: {title: {text: "dias até o deferimento (mediana)", font: {size: 11}}}}, "r-quadrada"),
        el("p", {class: "sub"}, `${fmt.n(td.especializada.n)} × ${fmt.n(td.comum.n)} processos · teste de Mann-Whitney: ${pv(td.mann_whitney_p)}`)), "Órgão julgador com 'falência', 'empresarial' ou 'recuperação' no nome", {span: "s5"}));
      if (cv.km) cards.push(cartao("Permanência sem convolação em falência (Kaplan-Meier)", grafico([{type: "scatter", mode: "lines", line: {shape: "hv", color: COR.verm, width: 2.4}, x: cv.km.curva.map((p) => p.t / 365.25), y: cv.km.curva.map((p) => p.s),
        hovertemplate: "%{x:.1f} anos: %{y:.0%} ainda sem falência<extra></extra>"}], {xaxis: {title: {text: "anos desde o ajuizamento", font: {size: 11}}}, yaxis: {tickformat: ".0%", range: [0, 1.02]}}, "r-media"),
        `DataJud – ${fmt.n(cv.km.eventos)} convolações em ${fmt.n(cv.km.n)} RJs; processos sem convolação contam até o último movimento`, {span: "s7"}));
      if ((d.bancos_recorrentes || []).length) { const b = [...d.bancos_recorrentes].reverse();
        cards.push(cartao("Bancos credores mais recorrentes", grafico([{type: "bar", orientation: "h", y: b.map((x) => x.banco), x: b.map((x) => x.processos), marker: {color: COR.ambar}, text: b.map((x) => fmt.n(x.processos)), textposition: "outside", cliponaxis: false,
          customdata: b.map((x) => x.valor), hovertemplate: "%{y}: %{x} processos · R$ %{customdata:,.0f}<extra></extra>"}], {xaxis: {showticklabels: false, showgrid: false}, yaxis: {type: "category"}, margin: {r: 30}}, "r-quadrada"), "Editais de credores (DJEN) – nº de processos em que o banco aparece", {span: "s5"})); }
      if ((d.grupos || []).length) cards.push(cartao("Grupos de empresas devedoras", tabela(d.grupos, [["nomes", "Empresas (exemplos)", null, "quebra"], ["n_empresas", "Empresas"], ["n_processos", "Processos"], ["ufs", "UF"], ["tribunais", "Tribunais"]], 30),
        "Empresas ligadas por aparecerem como devedoras no mesmo processo (litisconsórcio) ou em mais de um processo", {span: "s6"}));
      if ((d.recorrentes || []).length) cards.push(cartao("Empresas devedoras em mais de um processo", tabela(d.recorrentes, [["nome", "Empresa", (v, l) => v || ("raiz CNPJ " + l.raiz), "quebra"], ["processos", "Processos"]], 30), "Cabeçalho dos editais de credores", {span: "s6"}));
      if ((d.companhias_abertas || []).length) cards.push(cartao("Companhias abertas com processo identificado", tabela(d.companhias_abertas, [["nome", "Companhia", null, "quebra"], ["cvm_situacao", "Situação na CVM"], ["tribunal", "Tribunal"], ["processo", "Processo", (v) => fmt.cnj(v), "mono"]], 30), "CVM – Dados Abertos × partes identificadas", {span: "s12"}));
      const busca = el("input", {type: "search", placeholder: "Filtrar por empresa, número, tribunal ou órgão…", style: "max-width:420px;margin:0 0 10px"});
      const colsLista = [["processo", "Processo", (v) => fmt.cnj(v), "mono"], ["tribunal", "Tribunal"], ["tipo", "Tipo"], ["ajuizamento", "Ajuizamento", (v) => fmt.data(v)],
        ["devedora", "Devedora (edital)", null, "quebra"], ["partes_citadas", "Partes PJ na publicação", null, "quebra"], ["passivo", "Passivo", (v) => v ? fmt.rs(v) : "", "n"], ["n_credores", "Credores"],
        ["dias_deferimento", "Dias até deferimento"], ["fontes", "Fontes"]];
      const caixaLista = el("div", {}, tabela(d.lista, colsLista, 300));
      busca.addEventListener("input", () => { const q = busca.value.trim().toLowerCase();
        caixaLista.replaceChildren(tabela(q ? d.lista.filter((l) => [l.processo, l.tribunal, l.devedora, l.partes_citadas, l.orgao].join(" ").toLowerCase().includes(q)) : d.lista, colsLista, 300)); });
      cards.push(cartao("Processos identificados", el("div", {}, busca, caixaLista), "DJEN, editais de credores e DataJud. Pessoas físicas não são exibidas.", {span: "s12", sub: "Mais recentes primeiro (até 500)."}));
      return [...cab, k, grade(...cards)];
    });

    registrar("tendencia", "Tendência e previsão", G, "publico", async () => {
      const t = await publico("tendencia");
      const cab = titulo("Tendência, sazonalidade e previsão", "Três modelos concorrentes são avaliados fora da amostra; a previsão final combina os modelos com pesos proporcionais à precisão de cada um.");
      const nomesMes = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
      const saz = (span) => cartao("Sazonalidade mensal", grafico([{type: "bar", x: nomesMes, y: (t.indices_sazonais || []).map((v) => (v - 1) * 100),
        marker: {color: (t.indices_sazonais || []).map((v) => v >= 1 ? COR.verm : COR.teal)},
        text: (t.indices_sazonais || []).map((v) => { const x = Math.round((v - 1) * 100); return (x > 0 ? "+" : "") + fmt.n(x === 0 ? 0 : x) + "%"; }), textposition: "outside", cliponaxis: false,
        hovertemplate: "%{x}: %{y:+.1f}% vs. tendência<extra></extra>"}], {yaxis: {ticksuffix: "%", rangemode: "normal", zeroline: true, zerolinecolor: "#9AA7B5"}, xaxis: {type: "category"}, margin: {t: 20}}, "r-media"),
        "Decomposição clássica multiplicativa", {span, sub: "Desvio típico de cada mês em relação à tendência"});
      if (t.previa) return t.indices_sazonais ? [...cab, grade(saz("s12")), sentinela(), await portao()] : [...cab, preparando()];
      if (!t.meses) return [...cab, preparando()];
      const val = Object.entries(t.validacao || {}).map(([k, v]) => ({modelo: k, ...v, peso: (t.pesos_ensemble || {})[k]})).sort((a, b) => a.MASE - b.MASE);
      const ini = Math.max(0, t.meses.length - 36), xh = t.meses.slice(ini);
      const linhasModelos = Object.entries(t.previsao_modelos || {}).map(([k, v], i) => ({type: "scatter", mode: "lines", name: k, x: t.previsao_meses, y: v, line: {width: 1.6, color: [COR.teal, COR.roxo, COR.cinza][i % 3], dash: "dash"}, hovertemplate: "%{y:,.0f}<extra>" + k + "</extra>"}));
      const ens = t.previsao_ensemble || [];
      const ultX = t.meses[t.meses.length - 1], ultY = t.observado[t.observado.length - 1];
      return [...cab, grade(
        cartao("Previsão para os próximos 12 meses", grafico([
          {type: "scatter", mode: "lines", name: "Observado", x: xh, y: t.observado.slice(ini), line: {color: COR.azul, width: 2.2}, hovertemplate: "%{y:,.0f}<extra>observado</extra>"},
          {type: "scatter", mode: "lines", x: t.previsao_meses, y: ens.map((p) => p.sup), line: {width: 0}, showlegend: false, hoverinfo: "skip"},
          {type: "scatter", mode: "lines", name: "Intervalo de 80%", x: t.previsao_meses, y: ens.map((p) => p.inf), fill: "tonexty", fillcolor: "rgba(232,163,61,.2)", line: {width: 0}, hoverinfo: "skip"},
          ...linhasModelos,
          {type: "scatter", mode: "lines+markers", name: "Ensemble", x: [ultX, ...t.previsao_meses], y: [ultY, ...ens.map((p) => p.previsto)], line: {color: COR.ambar, width: 3}, marker: {size: 5}, hovertemplate: "%{y:,.0f}<extra>ensemble</extra>"}],
          {hovermode: "x unified", xaxis: {type: "date", tickformat: "%m/%Y", hoverformat: "%m/%Y"}, yaxis: {rangemode: "normal"}}, "r-media"), "Modelos do Observatório", {span: "s8", sub: "Últimos 36 meses observados e trajetória de cada modelo"}),
        cartao("Desempenho fora da amostra", el("div", {},
          tabela(val, [["modelo", "Modelo", null, "quebra-c"], ["MASE", "MASE", (v) => fmt.n(v, 2), "n"], ["MAPE_%", "Erro %", (v) => fmt.n(v, 1), "n"], ["peso", "Peso", (v) => v === undefined ? "–" : fmt.p(v * 100, 0), "n"]]),
          el("p", {class: "sub", style: "margin-top:8px"}, "Validação com origem móvel (horizonte de 6 meses). MASE < 1 indica desempenho melhor que repetir o mesmo mês do ano anterior.")), null, {span: "s4"}),
        saz("s6"),
        cartao("Regimes identificados", el("div", {}, grafico([{type: "scatter", mode: "lines", x: t.meses, y: t.observado, line: {color: "rgba(31,90,150,.35)", width: 1}, name: "observado", hoverinfo: "skip"},
          ...(t.regimes || []).map((r, i) => ({type: "scatter", mode: "lines", x: [r.de, r.ate], y: [r.media, r.media], line: {color: [COR.ambar, COR.verm, COR.teal, COR.roxo, COR.azul][i % 5], width: 4}, name: `${fmt.mes(r.de)}–${fmt.mes(r.ate)}`, hovertemplate: "média %{y:,.0f}<extra></extra>"}))],
          {xaxis: {type: "date", tickformat: "%Y"}, showlegend: false, hovermode: "closest"}, "r-media"),
          el("div", {class: "legenda-regimes"}, (t.regimes || []).map((r) => el("span", {}, el("b", {}, fmt.mes(r.de) + " a " + fmt.mes(r.ate)), " · média " + fmt.n(r.media, 0) + "/mês")))),
          "Segmentação binária com verossimilhança de Poisson e critério BIC", {span: "s6"}))];
    });

    registrar("macro", "Macroeconomia e juros", G, "publico", async () => {
      const d = await publico("macro");
      const cab = titulo("Ambiente macroeconômico e curva de juros", "Juros, crédito e inadimplência costumam anteceder os pedidos de recuperação judicial. Aqui estão as séries, as expectativas de mercado e a evidência estatística dessa relação.");
      if (!d.series || !d.series.length) return [...cab, preparando()];
      const ss = [...new Set(d.series.map((r) => r.serie))];
      const series = (span) => cartao("Juros, spread e inadimplência das empresas", grafico(ss.map((s, i) => ({type: "scatter", mode: "lines", name: ROT[s] || s, x: d.series.filter((r) => r.serie === s).map((r) => r.mes), y: d.series.filter((r) => r.serie === s).map((r) => r.valor),
        line: {width: 2, color: PAL[i]}, hovertemplate: "%{y:.2f}%<extra>" + (ROT[s] || s) + "</extra>"})), {hovermode: "x unified", xaxis: {type: "date", tickformat: "%Y", hoverformat: "%m/%Y"}, yaxis: {ticksuffix: "%"}}, "r-media"), "Banco Central – SGS", {span});
      if (d.previa) return [...cab, grade(series("s12")), sentinela(), await portao()];
      const curva = (cv) => { const c = (d.curva || []).filter((r) => r.curva === cv); const mo = ["-24m", "-12m", "-6m", "hoje"].filter((m) => c.some((r) => r.momento === m));
        return mo.map((m, i) => ({type: "scatter", mode: "lines+markers", name: m === "hoje" ? "Hoje" : m.replace("-", "há ").replace("m", " meses"), x: c.filter((r) => r.momento === m).map((r) => r.prazo), y: c.filter((r) => r.momento === m).map((r) => r.taxa),
          line: {width: m === "hoje" ? 3 : 1.6, color: m === "hoje" ? COR.navy : ["#C9D6E3", "#9DB4CC", "#5F87B0"][i]}, marker: {size: m === "hoje" ? 6 : 4}, hovertemplate: "%{x:.1f} anos: %{y:.2f}%<extra>" + m + "</extra>"})); };
      const corr = [...(d.correlacoes || [])].sort((a, b) => Math.abs(a.correlacao) - Math.abs(b.correlacao)).slice(-12);
      const g = [series("s8")];
      g.push(cartao("Expectativas de mercado", (d.focus || []).length ? tabela(d.focus, [["indicador", "Indicador"], ["ref", "Ano"], ["mediana", "Mediana", (v) => fmt.n(v, 2), "n"]]) : el("p", {class: "vazio"}, "Sem dados."), "Banco Central – Focus", {span: "s4"}));
      for (const cv of ["Prefixada", "Real (IPCA+)"]) if ((d.curva || []).some((r) => r.curva === cv)) g.push(cartao("Curva de juros " + (cv === "Prefixada" ? "prefixada" : "real (IPCA+)"), grafico(curva(cv), {hovermode: "closest", xaxis: {title: {text: "prazo (anos)", font: {size: 11}}, rangemode: "tozero"}, yaxis: {ticksuffix: "%", rangemode: "normal"}}, "r-media"), "Tesouro Transparente", {span: "s6", sub: "Estrutura a termo hoje e 6, 12 e 24 meses atrás"}));
      if (corr.length) g.push(cartao("O que antecede os pedidos de recuperação judicial", grafico([
        {type: "scatter", mode: "markers", x: corr.map((c) => c.correlacao), y: corr.map((c) => `${ROT[c.variavel] || c.variavel} · ${c.defasagem_meses}m`), marker: {size: 12, color: corr.map((c) => c.antecede_rj ? COR.ambar : COR.azul), line: {color: "#fff", width: 1.5}},
          error_x: {type: "data", symmetric: false, array: corr.map(() => 0), arrayminus: corr.map((c) => c.correlacao), color: "#C9D2DC", thickness: 2, width: 0},
          hovertemplate: "correlação %{x:.2f}<extra></extra>"}], {xaxis: {range: [-1, 1], zeroline: true, zerolinecolor: "#9AA7B5", title: {text: "correlação com pedidos de RJ (na defasagem de maior associação)", font: {size: 11}}}, yaxis: {type: "category", rangemode: "normal"}, margin: {l: 8}}, "r-media"),
        "Observatório – laranja: antecipa os pedidos (teste de Granger, p<5%)", {span: "s7"}));
      if (d.modelo) g.push(cartao("Modelo explicativo (binomial negativo)", el("div", {}, tabela(d.modelo.tabela.filter((r) => r.termo !== "constante"), [["termo", "Variável", (v) => rotulo(v), "quebra-c"], ["efeito_%", "Efeito", (v) => v === null || v === undefined ? "–" : (v > 0 ? "+" : "") + fmt.n(v, 1) + "%", "n"], ["p_valor", "Signif.", (v) => pv(v), "n"]]),
        el("p", {class: "sub", style: "margin-top:8px"}, `Pseudo-R² ${fmt.n(d.modelo.pseudo_r2, 2)} · ${d.modelo.n_meses} meses. Efeito = variação percentual esperada nos pedidos mensais para +1 unidade da variável.`)), null, {span: "s5"}));
      return [...cab, grade(...g)];
    });

    registrar("credores", "Credores e concentração", G, "publico", async () => {
      const d = await publico("credores");
      const cab = titulo("Credores, classes e concentração bancária", "Extraído dos editais de relação de credores publicados no Diário de Justiça Eletrônico Nacional (DJEN). Pessoas físicas são anonimizadas.");
      const corClasse = {"I – Trabalhista": COR.teal, "II – Garantia real": COR.azul, "III – Quirografário": COR.ambar, "IV – ME/EPP": COR.roxo, "Não informada": COR.cinza};
      const totC = (d.classes || []).reduce((s, x) => s + (x.valor || 0), 0);
      const pizza = (span) => cartao("Passivo por classe de crédito", grafico([{type: "pie", hole: 0.62, sort: false, direction: "clockwise", labels: (d.classes || []).map((x) => x.classe), values: (d.classes || []).map((x) => x.valor),
        marker: {colors: (d.classes || []).map((x) => corClasse[x.classe] || COR.cinza), line: {color: "#fff", width: 2}}, textinfo: "percent", textfont: {color: "#fff", size: 12},
        hovertemplate: "%{label}<br>R$ %{value:,.0f}<br>%{percent}<extra></extra>"}], {legend: {orientation: "v", x: 1, y: 0.5, xanchor: "left", yanchor: "middle"}, margin: {r: 10},
        annotations: [{text: fmt.rs(totC), showarrow: false, font: {size: 15, color: COR.navy}, x: 0.5, y: 0.5, xref: "paper", yref: "paper"}]}, "r-quadrada"), "DJEN – editais", {span, sub: "Lei 11.101/2005, art. 41"});
      if (d.previa) return (d.classes || []).length ? [...cab, grade(pizza("s12")), sentinela(), await portao()] : [...cab, preparando()];
      if (!d.processos || !d.processos.length) return [...cab, preparando()];
      const tot = d.processos.reduce((s, p) => s + (p.passivo || 0), 0);
      const rk = {}; for (const b of d.bancos || []) rk[b.banco] = (rk[b.banco] || 0) + b.valor;
      const totB = Object.values(rk).reduce((a, b) => a + b, 0);
      const ord = Object.entries(rk).sort((a, b) => a[1] - b[1]).slice(-12);
      const c = d.concentracao || {};
      const lz = c.lorenz_passivo || [];
      const dist = c.distribuicao_hhi || {};
      return [...cab,
        el("div", {class: "kpis"}, kpi(fmt.rs(tot), "Passivo listado", fmt.n(d.processos.length) + " processos com lista vigente"),
          kpi(fmt.p(totB / tot * 100), "Participação dos bancos", "no passivo listado"),
          kpi(c.hhi_bancos_agregado ? fmt.n(c.hhi_bancos_agregado) : "–", "HHI dos bancos credores", c.faixa_agregado ? "concentração " + c.faixa_agregado : ""),
          kpi(c.gini_passivo !== null && c.gini_passivo !== undefined ? fmt.n(c.gini_passivo, 2) : "–", "Gini do passivo", "desigualdade de porte entre as recuperandas")),
        grade(pizza("s5"),
          cartao("Bancos credores – valor listado e participação", grafico([{type: "bar", orientation: "h", y: ord.map((x) => x[0]), x: ord.map((x) => x[1]), marker: {color: ord.map((x) => x[0] === "CAIXA" || x[0] === "Banco do Brasil" || x[0] === "BNDES" ? COR.azul : COR.cinza)},
            text: ord.map((x) => fmt.p(x[1] / totB * 100)), textposition: "outside", cliponaxis: false, hovertemplate: "%{y}<br>R$ %{x:,.0f}<extra></extra>"}],
            {xaxis: {showticklabels: false, showgrid: false}, yaxis: {type: "category"}, margin: {r: 46}}, "r-quadrada"), "DJEN – editais · azul: bancos públicos", {span: "s7"}),
          cartao("Curva de Lorenz do passivo", grafico([{type: "scatter", mode: "lines", x: [0, 1], y: [0, 1], line: {color: "#9AA7B5", dash: "dot", width: 1}, name: "Igualdade perfeita", hoverinfo: "skip"},
            {type: "scatter", mode: "lines", x: lz.map((p) => p.pop), y: lz.map((p) => p.valor), fill: "tonexty", fillcolor: "rgba(232,163,61,.18)", line: {color: COR.ambar, width: 2.6}, name: "Recuperandas",
              hovertemplate: "%{x:.0%} das empresas concentram %{y:.0%} do passivo<extra></extra>"}],
            {xaxis: {tickformat: ".0%", range: [0, 1], title: {text: "% acumulado de recuperandas (da menor para a maior)", font: {size: 11}}}, yaxis: {tickformat: ".0%", range: [0, 1]}, showlegend: false,
              annotations: [{x: 0.3, y: 0.82, xref: "x", yref: "y", showarrow: false, text: "Gini " + fmt.n(c.gini_passivo, 2), font: {size: 14, color: COR.navy}}]}, "r-quadrada"), "Observatório", {span: "s6"}),
          cartao("Concentração bancária por processo", grafico([{type: "bar", x: ["Baixa (<1.500)", "Moderada (1.500–2.500)", "Alta (>2.500)"], y: [dist.baixa || 0, dist.moderada || 0, dist.alta || 0], marker: {color: [COR.teal, COR.ambar, COR.verm]},
            text: [dist.baixa || 0, dist.moderada || 0, dist.alta || 0].map((v) => fmt.n(v)), textposition: "outside", cliponaxis: false, hovertemplate: "%{x}: %{y} processos<extra></extra>"}],
            {xaxis: {type: "category"}, yaxis: {title: {text: "processos", font: {size: 11}}}}, "r-quadrada"), "Índice Herfindahl-Hirschman – critérios CADE/DoJ", {span: "s6", sub: c.hhi_mediano_processo ? "HHI mediano por processo: " + fmt.n(c.hhi_mediano_processo) : ""}),
          cartao("Maiores passivos listados", tabela(d.processos, [["devedora", "Devedora (cabeçalho do edital)", (v) => v || "não identificada", "quebra"], ["tribunal", "Tribunal"], ["rj_re", "Tipo"], ["passivo", "Passivo", (v) => fmt.rs(v), "n"], ["bancos_%", "% bancos", (v) => fmt.p(v), "n"], ["confianca", "Extração", (v) => el("span", {class: "selo " + (v === "Alta" ? "ok" : v === "Média" ? "al" : "")}, v)]], 50),
            "DJEN – editais. Confiança da extração: conferência com os totais declarados", {span: "s12", sub: `${fmt.n(d.lista_em_anexo || 0)} editais remetem a lista a anexo externo e não entram nos números.`}))];
    });

    registrar("metodologia", "Como coletamos", G, "publico", async () => {
      const c = await publico("coleta");
      const etapas = (c.etapas || []);
      const vol = c.volumes || {};
      return [...titulo("Como coletamos, cruzamos e calculamos", "Todas as informações vêm de fontes públicas oficiais. Esta página mostra de onde vem cada dado, como as bases são cruzadas, quais métodos são aplicados e quando foi a última atualização."),
        el("div", {class: "fluxo"},
          el("div", {class: "p"}, el("h4", {}, "Coleta"), el("p", {}, "Consulta automática às APIs públicas do CNJ (DataJud e DJEN), da CVM, do Banco Central e do Tesouro.")),
          el("div", {class: "p"}, el("h4", {}, "Cruzamento"), el("p", {}, "Os números de processo do DJEN são consultados um a um no DataJud; partes, credores e CNPJs são ligados entre si e à CVM.")),
          el("div", {class: "p"}, el("h4", {}, "Cálculo"), el("p", {}, "Tendência, sazonalidade, previsão validada, tempos processuais, concentração de credores e relação com juros e crédito.")),
          el("div", {class: "p"}, el("h4", {}, "Publicação"), el("p", {}, "Os resultados agregados são publicados neste portal. Pessoas físicas não são exibidas."))),
        el("div", {style: "height:20px"}),
        grade(cartao("Fontes e última atualização", tabela(etapas, [["fonte", "Fonte", null, "quebra-c"], ["descricao", "O que é coletado", null, "quebra"], ["ultima", "Última execução", fmt.d],
          ["situacao", "Situação", (v) => v ? el("span", {class: "selo " + (v === "concluída" ? "ok" : v === "falha" ? "er" : "al")}, v) : "não executada"], ["linhas", "Registros"]]), null, {span: "s12"}),
        cartao("Volume das bases", tabela(Object.entries(vol).map(([k, v]) => ({base: {datajud_mensal: "Contagens mensais DataJud (tribunal × classe × mês)", datajud_processos: "Processos consultados no DataJud", djen_publicacoes: "Publicações do DJEN",
          djen_editais: "Editais de credores", credores: "Credores extraídos", cvm_insolvencia: "Companhias abertas em insolvência (CVM)", macro_mensal: "Pontos de séries macroeconômicas", curva: "Pontos da curva de juros",
          processos: "Processos identificados (cruzamento)", partes: "Partes identificadas (cruzamento)", grupos: "Grupos de devedoras"}[k] || k, registros: v}))), null, {span: "s6"}),
        cartao("Regras do cruzamento", el("ul", {class: "texto", style: "font-size:13px;margin:0;padding-left:18px"},
          el("li", {}, "Devedora: somente quando o CNPJ aparece no cabeçalho do edital de credores."),
          el("li", {}, "CNPJs citados em outras publicações são registrados como 'citados', sem presumir se são devedores ou credores."),
          el("li", {}, "Tipo do processo: classe no DataJud (129 RJ, 128 RE, 108 falência); na falta, a classe informada no DJEN ou o tipo do edital."),
          el("li", {}, "Datas de deferimento, concessão, convolação e encerramento: primeiro movimento do DataJud cujo nome contém o termo correspondente."),
          el("li", {}, "Grupos: empresas que aparecem juntas como devedoras no mesmo processo ou em mais de um processo."),
          el("li", {}, "Destinatários sem característica de pessoa jurídica não têm o nome gravado.")), null, {span: "s6"})),
        el("div", {class: "texto"},
          el("h2", {}, "Métodos estatísticos"),
          el("h3", {}, "Tendência e sazonalidade"), el("p", {}, "Decomposição clássica multiplicativa: tendência por média móvel centrada 2×12 e índices sazonais pela mediana das razões, robusta a meses atípicos."),
          el("h3", {}, "Previsão"), el("p", {}, "Três modelos concorrentes – Holt-Winters (suavização exponencial tripla em escala logarítmica, parâmetros otimizados por Nelder-Mead), regressão binomial negativa com tendência e efeitos mensais, e o ingênuo sazonal – são avaliados por validação com origem móvel. A previsão final é um ensemble com pesos inversamente proporcionais ao quadrado do MASE. A faixa mostra o intervalo de 80%."),
          el("h3", {}, "Mudança de regime"), el("p", {}, "Segmentação binária com verossimilhança de Poisson e penalidade BIC, com segmentos mínimos de 12 meses."),
          el("h3", {}, "Tempos processuais"), el("p", {}, "Mediana de dias entre o ajuizamento e o deferimento do processamento; comparação entre varas especializadas e comuns pelo teste de Mann-Whitney; permanência sem convolação em falência pelo estimador de Kaplan-Meier, com processos ainda em curso tratados como observações censuradas."),
          el("h3", {}, "Relação com a macroeconomia"), el("p", {}, "Correlação na defasagem de maior associação (0 a 12 meses), teste de causalidade de Granger nas primeiras diferenças e regressão binomial negativa (GLM) com as variáveis mais associadas de cada família, descartando pares com correlação acima de 0,85."),
          el("h3", {}, "Concentração e desigualdade"), el("p", {}, "Índice Herfindahl-Hirschman (0 a 10.000) dos créditos bancários, por processo e agregado, com os cortes usados pelo CADE e pelo Departamento de Justiça dos EUA; coeficiente de Gini e curva de Lorenz do passivo listado."),
          el("h2", {}, "Validação"), el("p", {}, "As rotinas estatísticas têm testes automatizados e foram conferidas contra pacotes de referência (statsmodels e SciPy)."),
          el("h2", {}, "Limitações"), el("ul", {}, el("li", {}, "O DataJud depende do envio dos tribunais; meses recentes podem ser revisados para cima."),
            el("li", {}, "O DJEN é consultado por janela de dias; processos sem publicação recente não entram na lista de processos identificados."),
            el("li", {}, "Editais que remetem a lista a anexo externo não são lidos; créditos extraconcursais (alienação e cessão fiduciária) não constam das listas."),
            el("li", {}, "Marcos processuais dependem do nome dado ao movimento pelo tribunal."),
            el("li", {}, "Associação estatística não implica causalidade; previsões são cenários, não garantias.")))];
    });

    registrar("privacidade", "Privacidade", G, "publico", async () => {
      const p = await publico("privacidade");
      return [...titulo("Privacidade e uso dos dados"), el("div", {class: "texto"},
        el("h2", {}, "Dados do cadastro"), el("p", {}, "Para liberar o conteúdo completo, pedimos nome, e-mail, perfil e, opcionalmente, organização e interesse no tema. Não pedimos documentos."),
        el("h2", {}, "Para que usamos"), el("ul", {}, el("li", {}, "Liberar o acesso ao conteúdo completo neste navegador."), el("li", {}, "Entender o público do Observatório (contagem por perfil)."),
          el("li", {}, "Enviar avisos de atualização, somente se você marcar essa opção.")),
        el("h2", {}, "Como guardamos"), el("ul", {}, el("li", {}, "O navegador recebe um código de acesso aleatório; no servidor fica apenas a sua versão cifrada (hash)."),
          el("li", {}, `O acesso liberado vale por ${fmt.n(p.validade_cadastro_dias)} dias neste navegador.`),
          el("li", {}, `Cadastros sem acesso por ${fmt.n(p.retencao_dias)} dias são apagados automaticamente.`),
          el("li", {}, "Os dados não são vendidos nem cedidos a terceiros.")),
        el("h2", {}, "Seus direitos"), el("p", {}, "Você pode pedir acesso, correção ou exclusão dos seus dados a qualquer momento pelo ", el("a", {href: "#contato"}, "Fale conosco"),
          p.email ? [" ou pelo e-mail ", el("strong", {}, p.email)] : null, "."),
        p.controlador ? [el("h2", {}, "Responsável"), el("p", {}, p.controlador)] : null,
        el("h2", {}, "Dados exibidos no portal"), el("p", {}, "O portal exibe informações de processos públicos (número, tribunal, empresas e credores pessoa jurídica). Pessoas físicas não são identificadas: credores pessoa física aparecem apenas como “PESSOA FÍSICA” e destinatários sem característica de empresa não têm o nome gravado."))];
    });

    registrar("contato", "Fale conosco", G, "publico", async () => {
      const f = el("form", {class: "form-grade", style: "max-width:720px"}, el("label", {}, "Nome", el("input", {name: "nome", required: true, maxlength: 120, autocomplete: "name"})),
        el("label", {}, "E-mail", el("input", {name: "email", type: "email", required: true, maxlength: 200, autocomplete: "email"})),
        el("label", {style: "grid-column:1/-1"}, "Assunto", el("input", {name: "assunto", required: true, maxlength: 160})),
        el("label", {style: "grid-column:1/-1"}, "Mensagem", el("textarea", {name: "mensagem", required: true, maxlength: 4000, rows: 6})),
        el("input", {name: "site", class: "isca", tabindex: "-1", autocomplete: "off", "aria-hidden": "true"}),
        el("div", {}, el("button", {class: "btn", type: "submit"}, "Enviar mensagem")));
      const m = el("p", {class: "msg", role: "status"});
      f.addEventListener("submit", async (ev) => { ev.preventDefault(); try { const r = await api("/api/v1/sac/contato", {method: "POST", corpo: Object.fromEntries(new FormData(f))}); f.reset(); m.className = "msg ok"; m.textContent = "Mensagem recebida. Protocolo " + r.protocolo + "."; } catch (e) { m.className = "msg"; m.textContent = e.message; } });
      const sair = E.visitante && !E.usuario ? el("p", {class: "sub"}, "Cadastrado neste navegador. ", el("button", {class: "btn-link", type: "button", on: {click: async () => { await api("/api/v1/publico/cadastro/sair", {method: "POST"}); E.visitante = null; E.liberado = !E.exigido; E.cache = {}; atualizarTopo(); montarMenu(); rotear(); }}}, "Encerrar acesso neste navegador")) : null;
      return [...titulo("Fale conosco", "Dúvidas, sugestões, correções sobre os dados ou pedidos sobre seus dados pessoais. Respondemos pelo e-mail informado."), el("section", {class: "cartao"}, f, m), sair];
    });
    ["processos", "tendencia", "macro", "credores"].forEach((k) => { E.views[k].cadastro = true; });

    // ---------------------------------------------------- área restrita
    const R = "Área restrita";
    registrar("carteira", "Carteira Atacado", R, "carteira", async () => {
      const d = await api("/api/v1/painel/carteira"); const r = d.resumo;
      const cab = titulo("Carteira Atacado – clientes em RJ, RE e falência", "Informação interna e sigilosa. Taxas com intervalo de confiança de Wilson (95%).");
      if (!r) return [...cab, vazio("A base de clientes ainda não foi importada.")];
      const barraIC = (dim, nome) => {
        const t = d.taxas[dim]; if (!t) return null;
        const l = [...t.linhas].filter((x) => x.cnpjs >= 30).sort((a, b) => a.taxa_rj - b.taxa_rj);
        return cartao(`Taxa de RJ por ${nome}`, grafico([{type: "bar", orientation: "h", y: l.map((x) => x.categoria), x: l.map((x) => x.taxa_rj), marker: {color: COR.azul},
          error_x: {type: "data", symmetric: false, array: l.map((x) => (x.ic95_sup ?? x.taxa_rj) - x.taxa_rj), arrayminus: l.map((x) => x.taxa_rj - (x.ic95_inf ?? x.taxa_rj)), color: COR.ambar, thickness: 1.5, width: 3},
          customdata: l.map((x) => [x.rj, x.cnpjs]), hovertemplate: "%{y}: %{x:.2f}% (%{customdata[0]} de %{customdata[1]})<extra></extra>"}], {xaxis: {ticksuffix: "%"}, yaxis: {type: "category"}}, "r-quadrada"), "Base de clientes Atacado · qui² " + pv(t.qui2_p), {span: "s6"});
      };
      const g = [barraIC("seg2", "segmento SICLI"), barraIC("setor", "setor (CNAE)"), barraIC("faixa_fat", "faixa de faturamento"), barraIC("qualidade", "qualidade do cadastro")];
      if ((d.processos || []).length) g.push(cartao("Clientes com processo identificado no cruzamento", tabela(d.processos, [["razao", "Cliente", null, "quebra"], ["unidade", "Unidade"], ["papel", "Papel"], ["processo", "Processo", (v) => fmt.cnj(v), "mono"], ["tribunal", "Tribunal"], ["tipo", "Tipo"], ["ajuizamento", "Ajuizamento", (v) => fmt.data(v)], ["passivo", "Passivo", (v) => v ? fmt.rs(v) : "", "n"]], 100),
        "Carteira × partes (DJEN, editais e DataJud) pela raiz do CNPJ", {span: "s12"}));
      if (d.foco_setor) g.push(cartao(`Segmento ${r.foco} – taxa de RJ por setor`, tabela(d.foco_setor, [["setor", "Setor"], ["cnpjs", "CNPJs"], ["rj", "Em RJ"], ["taxa_rj", "Taxa %"]]), null, {span: "s6"}));
      for (const [dim, nome] of [["segmento", "código SICLI"], ["carteira", "carteira"], ["unidade", "unidade"]]) {
        const t = d.taxas[dim]; if (!t) continue;
        g.push(cartao(`RJ por ${nome} (mín. 50 CNPJs)`, tabela([...t.linhas].filter((x) => x.cnpjs >= 50).sort((a, b) => b.taxa_rj - a.taxa_rj), [["categoria", nome], ["cnpjs", "CNPJs"], ["rj", "Em RJ"], ["taxa_rj", "Taxa %"], ["ic95_inf", "IC inf."], ["ic95_sup", "IC sup."]], 20),
          dim !== "unidade" ? "Taxas muito altas podem indicar carteiras de destino de clientes já em dificuldade" : null, {span: "s6"}));
      }
      if (d.logit) g.push(cartao(`Regressão logística – propensão à RJ (AUC ${fmt.n(d.logit.auc, 2)})`, tabela(d.logit.tabela, [["variavel", "Variável", (v) => v.replace("seg2=", "segmento ").replace("faixa_fat=", "faturamento ").replace("setor=", "setor ").replace("regiao=", "região "), "quebra-c"], ["odds_ratio", "Razão de chances"], ["p_valor", "p-valor", (v) => pv(v), "n"]], 40), null, {span: "s6"}));
      g.push(cartao("Grupos econômicos com CNPJs em insolvência", tabela(d.grupos, [["exemplo", "Grupo (exemplo)", null, "quebra"], ["cnpjs_insolv", "Em insolvência"], ["cnpjs_grupo", "CNPJs no grupo"], ["cnpjs_sem_restricao", "Sem restrição"]], 30), null, {span: "s6"}));
      if (d.vigilancia && d.vigilancia.length) g.push(cartao("Lista de vigilância – clientes sem restrição com maior propensão", tabela(d.vigilancia, [["razao", "Razão social", null, "quebra"], ["cnpj", "CNPJ"], ["unidade", "Unidade"], ["setor", "Setor"], ["uf", "UF"], ["qualidade", "Cadastro"], ["contagio_grupo", "Grupo afetado", (v) => v ? "sim" : ""], ["propensao_%", "Propensão %"]], 60), "Triagem interna – não é decisão de crédito", {span: "s12"}));
      return [...cab, el("div", {class: "kpis"}, kpi(fmt.n(r.rj), "CNPJs com RJ", fmt.p(r.taxa_rj, 2) + " da base de " + fmt.n(r.cnpjs)), kpi(fmt.p(r.foco_taxa_rj, 2), "Taxa de RJ – segmento " + r.foco, fmt.p(r.foco_part_rj) + " das RJs da base"),
        kpi(fmt.n(r.com_processo), "Clientes com processo identificado", "cruzamento com DJEN/editais/DataJud"), kpi(fmt.n(r.contagio), "CNPJs sem restrição em grupos afetados", fmt.n(r.grupos_multi_rj) + " grupos com mais de um CNPJ em RJ")), grade(...g.filter(Boolean))];
    });

    const PSI = {
      casos: [["identificacao", "Identificação"], ["setor", "Setor"], ["uf", "UF"], ["data_concessao", "Data da concessão"], ["data_pedido_rj", "Data do pedido de RJ"], ["modalidade", "Modalidade"], ["valor_mil", "Valor (R$ mil)"], ["garantias", "Garantias"], ["rating", "Rating"], ["premissas", "Premissas do voto"], ["evidencia", "Evidência (documento/página)"]],
      indicadores: [["caso_id", "Caso (nº)"], ["indicador", "Indicador"], ["v_concessao", "Valor na concessão"], ["v_pre_rj", "Valor pré-RJ"], ["considerado", "Considerado no voto (Sim/Parcial/Não)"], ["evidencia", "Evidência"]],
      fatores: [["caso_id", "Caso (nº)"], ["fator", "Fator"], ["categoria", "Categoria"], ["presente", "Presente nos documentos (Sim/Não)"], ["tratamento", "Tratamento no voto (Considerado/Parcial/Não considerado)"], ["impacto", "Impacto 1–5"], ["evidencia", "Evidência"]],
      recomendacoes: [["recomendacao", "Recomendação"], ["processo", "Processo (Concessão/Monitoramento/Gestão)"], ["impacto", "Impacto 1–5"], ["aplicabilidade", "Aplicabilidade 1–5"], ["casos", "Casos relacionados"], ["status", "Situação"]]};
    registrar("psi", "PSI 15508", R, "psi", async () => {
      const box = el("div"); const abas = el("div", {class: "abas", role: "tablist"});
      const ir = async (t) => {
        abas.querySelectorAll("button").forEach((b) => b.classList.toggle("ativo", b.dataset.t === t));
        const lst = await api("/api/v1/psi/" + t); const f = el("form", {class: "form-grade"}); const msg = el("p", {class: "msg"});
        PSI[t].forEach(([k, r]) => f.append(el("label", {}, r, k === "premissas" || k === "recomendacao" ? el("textarea", {name: k, rows: 2, maxlength: 4000}) : el("input", {name: k, maxlength: 4000}))));
        f.append(el("input", {type: "hidden", name: "id"}), el("div", {}, el("button", {class: "btn", type: "submit"}, "Salvar"), " ", el("button", {type: "reset", class: "btn btn-sec"}, "Limpar")), msg);
        f.addEventListener("submit", async (ev) => { ev.preventDefault(); try { await api("/api/v1/psi/" + t, {method: "POST", corpo: Object.fromEntries(new FormData(f))}); ir(t); } catch (e) { msg.textContent = e.message; } });
        const cols = [["id", "Nº"], ...PSI[t], ["id", "", (v, l) => el("span", {}, el("button", {class: "btn-link", type: "button", on: {click: () => { for (const [k] of PSI[t]) f.elements[k].value = l[k] ?? ""; f.elements.id.value = l.id; }}}, "editar"), " ",
          el("button", {class: "btn-link", type: "button", on: {click: async () => { if (confirm("Excluir registro?")) { await api(`/api/v1/psi/${t}/${v}`, {method: "DELETE"}); ir(t); } }}}, "excluir"))]];
        const extra = [];
        if (t === "recomendacoes" && lst.length) extra.push(cartao("Matriz impacto × aplicabilidade", grafico([{type: "scatter", mode: "markers+text", text: lst.map((r) => String(r.id)), textposition: "middle center", textfont: {color: "#fff", size: 11},
          x: lst.map((r) => r.aplicabilidade), y: lst.map((r) => r.impacto), marker: {size: lst.map((r) => 16 + 2 * (r.impacto || 0) * (r.aplicabilidade || 0) / 3), color: lst.map((r) => (r.impacto >= 4 && r.aplicabilidade >= 4) ? COR.verm : COR.azul), opacity: 0.9},
          hovertemplate: "%{text}<extra></extra>"}], {xaxis: {range: [0.5, 5.5], dtick: 1, title: {text: "Aplicabilidade"}}, yaxis: {range: [0.5, 5.5], dtick: 1, title: {text: "Impacto"}},
          shapes: [{type: "rect", x0: 3.5, x1: 5.5, y0: 3.5, y1: 5.5, fillcolor: "rgba(200,85,61,.07)", line: {width: 0}}],
          annotations: [{x: 5.4, y: 5.4, text: "Fazer já", showarrow: false, xanchor: "right", font: {color: COR.verm, size: 11}}]}, "r-quadrada"), null, {span: "s6"}));
        if (t === "fatores" && lst.length) {
          const lac = lst.filter((r) => r.presente === "Sim" && (r.tratamento === "Não considerado" || r.tratamento === "Parcial"));
          const cats = [...new Set(lac.map((r) => r.categoria))], casos = [...new Set(lac.map((r) => r.caso_id))];
          if (lac.length) extra.push(cartao("Mapa de lacunas (peso = impacto)", grafico([{type: "heatmap", colorscale: [[0, "#FFF6E8"], [1, COR.verm]], x: casos.map((c) => "Caso " + c), y: cats, xgap: 3, ygap: 3,
            z: cats.map((c) => casos.map((k) => lac.filter((r) => r.categoria === c && r.caso_id === k).reduce((s, r) => s + (r.impacto || 3) * (r.tratamento === "Parcial" ? 0.5 : 1), 0)))}], {yaxis: {type: "category"}}, "r-quadrada"), null, {span: "s6"}));
        }
        box.replaceChildren(grade(cartao("Registro", f, null, {span: extra.length ? "s6" : "s12"}), ...extra, cartao("Registros", tabela(lst, cols), null, {span: "s12"})));
      };
      for (const t of Object.keys(PSI)) abas.append(el("button", {"data-t": t, role: "tab", on: {click: () => ir(t)}}, t[0].toUpperCase() + t.slice(1)));
      ir("casos");
      return [...titulo("PSI 15508 – Análise crítica de crédito a empresas que entraram em RJ", "As conclusões devem se basear exclusivamente nos documentos disponibilizados; informe sempre a evidência."),
        el("div", {class: "info"}, "a) Fundamentos da concessão → Casos e Indicadores · b) Fatores não considerados → Fatores · c) Prevenir, monitorar e mitigar → Recomendações"), abas, box];
    });

    registrar("conta", "Minha conta", R, null, async () => {
      const a = await api("/api/v1/conta/assinatura"); const ses = await api("/api/v1/conta/sessoes");
      const fs = el("form", {}, el("label", {}, "Senha atual", el("input", {type: "password", name: "atual", autocomplete: "current-password", required: true})),
        el("label", {}, "Nova senha", el("input", {type: "password", name: "nova", autocomplete: "new-password", required: true})), el("button", {class: "btn", type: "submit"}, "Alterar senha"));
      const ms = el("p", {class: "msg"});
      fs.addEventListener("submit", async (ev) => { ev.preventDefault(); try { const r = await api("/api/v1/conta/senha", {method: "POST", corpo: Object.fromEntries(new FormData(fs))}); fs.reset(); ms.className = "msg ok"; ms.textContent = r.mensagem; E.usuario.trocar_senha = false; } catch (e) { ms.className = "msg"; ms.textContent = e.message; } });
      const t2 = el("div");
      const ini2 = async () => {
        const r = await api("/api/v1/conta/2fa/iniciar", {method: "POST"}); const inp = el("input", {maxlength: 6, inputmode: "numeric"}); const m = el("p", {class: "msg"});
        t2.replaceChildren(el("p", {}, "Cadastre esta chave no aplicativo autenticador:"), el("code", {}, r.segredo), el("label", {}, "Código gerado", inp),
          el("button", {class: "btn", on: {click: async () => { try { const k = await api("/api/v1/conta/2fa/confirmar", {method: "POST", corpo: {codigo: inp.value}}); t2.replaceChildren(el("p", {class: "msg ok"}, "Verificação em duas etapas ativada. Guarde os códigos de recuperação:"), el("code", {}, k.codigos_recuperacao.join("  "))); } catch (e) { m.textContent = e.message; } }}}, "Confirmar"), m);
      };
      t2.append(E.usuario.dois_fatores ? el("p", {}, el("span", {class: "selo ok"}, "ativa"), " Verificação em duas etapas") : el("button", {class: "btn", on: {click: ini2}}, "Ativar verificação em duas etapas"));
      return [...titulo("Minha conta", E.usuario.trocar_senha ? "Defina uma nova senha para continuar." : null), grade(
        cartao("Dados", el("div", {}, el("p", {}, "Nome: ", E.usuario.nome), el("p", {}, "E-mail: ", E.usuario.email), el("p", {}, "Plano: ", a.assinatura ? a.assinatura.plano : "–"),
          el("p", {}, "Validade: ", a.assinatura && a.assinatura.fim ? new Date(a.assinatura.fim * 1000).toLocaleDateString("pt-BR") : "–")), null, {span: "s4"}),
        cartao("Senha", el("div", {}, fs, ms, el("p", {class: "sub"}, "Mínimo de 12 caracteres, com maiúsculas, minúsculas, números e símbolos.")), null, {span: "s4"}),
        cartao("Verificação em duas etapas", t2, null, {span: "s4"}),
        cartao("Sessões ativas", el("div", {}, tabela(ses, [["navegador", "Navegador", null, "quebra"], ["ip", "IP"], ["visto", "Último uso", fmt.d], ["atual", "", (v) => v ? "esta sessão" : ""]]),
          el("p", {}, el("button", {class: "btn btn-sec", on: {click: async () => { await api("/api/v1/conta/sessoes/encerrar", {method: "POST"}); abrir("conta"); }}}, "Encerrar outras sessões"))), null, {span: "s12"}))];
    });

    registrar("suporte", "Suporte (SAC)", R, "sac", async () => {
      const lst = await api("/api/v1/sac/chamados"); const det = el("div");
      const f = el("form", {}, el("label", {}, "Categoria", el("select", {name: "categoria"}, ["Dúvida", "Problema técnico", "Acesso e assinatura", "Sugestão", "Dados"].map((c) => el("option", {}, c)))),
        el("label", {}, "Assunto", el("input", {name: "assunto", maxlength: 160, required: true})), el("label", {}, "Mensagem", el("textarea", {name: "mensagem", rows: 4, maxlength: 4000, required: true})), el("button", {class: "btn", type: "submit"}, "Abrir chamado"));
      const m = el("p", {class: "msg"});
      f.addEventListener("submit", async (ev) => { ev.preventDefault(); try { const r = await api("/api/v1/sac/chamados", {method: "POST", corpo: Object.fromEntries(new FormData(f))}); m.className = "msg ok"; m.textContent = "Chamado aberto: " + r.protocolo; setTimeout(() => abrir("suporte"), 900); } catch (e) { m.className = "msg"; m.textContent = e.message; } });
      const ver = async (id) => {
        const d = await api("/api/v1/sac/chamados/" + id); const t = el("textarea", {rows: 3, maxlength: 4000});
        det.replaceChildren(grade(cartao(`Chamado ${d.chamado.protocolo} – ${d.chamado.assunto}`, el("div", {}, el("p", {}, el("span", {class: "selo"}, d.chamado.situacao)),
          el("div", {class: "chat"}, d.mensagens.map((x) => el("div", {class: "m " + x.autor}, el("div", {class: "q"}, (x.autor === "suporte" ? "Suporte" : "Você") + " · " + fmt.d(x.quando)), x.texto))),
          el("label", {}, "Responder", t), el("button", {class: "btn", on: {click: async () => { await api(`/api/v1/sac/chamados/${id}/mensagem`, {method: "POST", corpo: {texto: t.value}}); ver(id); }}}, "Enviar")), null, {span: "s12"})));
      };
      return [...titulo("Suporte", "Abra e acompanhe seus chamados"), grade(cartao("Novo chamado", el("div", {}, f, m), null, {span: "s5"}),
        cartao("Meus chamados", tabela(lst, [["protocolo", "Protocolo"], ["assunto", "Assunto", null, "quebra"], ["situacao", "Situação", (v) => el("span", {class: "selo"}, v)], ["atualizado", "Atualizado", fmt.d],
          ["id", "", (v) => el("button", {class: "btn-link", on: {click: () => ver(v)}}, "abrir")]]), null, {span: "s7"})), det];
    });
  }

  // API mínima exposta ao módulo do mantenedor (carregado só para ele)
  window.MRJ = Object.freeze({pv, el, api, tabela, grafico, cartao: (t, c, f, o) => cartao(t, c, f, o || {span: "s6"}), kpi, titulo, vazio, fmt, registrar,
    abrir: (id) => { location.hash = "#" + id; abrir(id); }, montarMenu, grade, COR});
  document.addEventListener("DOMContentLoaded", iniciar);
})();
