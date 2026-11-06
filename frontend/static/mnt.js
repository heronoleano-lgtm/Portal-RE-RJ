/* Painel do MANTENEDOR – arquivo entregue pelo servidor somente a sessões com perfil mantenedor. */
"use strict";
(() => {
  const {el, api, tabela, cartao, kpi, titulo, fmt, registrar, abrir, grade} = window.MRJ;
  const G = "Administração";
  const selo = (v, ok) => el("span", {class: "selo " + (ok ? "ok" : "er")}, v);
  const msg = () => { const m = el("p", {class: "msg"}); m.ok = (t) => { m.className = "msg ok"; m.textContent = t; }; m.er = (e) => { m.className = "msg"; m.textContent = e.message || e; }; return m; };

  registrar("mnt-resumo", "Visão geral", G, null, async () => {
    const r = await api("/api/v1/mnt/resumo");
    const chk = (r.etapas || []).map((e) => el("label", {class: "check", style: "display:inline-flex;margin-right:14px"}, el("input", {type: "checkbox", value: e, checked: (r.padrao || []).includes(e)}), e));
    const m = msg(); const up = el("input", {type: "file", accept: ".xlsx"});
    const it = r.integracao;
    const base = r.edicao === "publica"
      ? cartao("Edição pública", el("p", {}, "Este servidor opera somente com dados públicos. Carteira de clientes e PSI ficam desativados; para atualizar os dados, use 'exportar-publico' na máquina interna e 'importar-publico' aqui, ou execute a coleta."))
      : cartao("Base de clientes Atacado (DB5186)", el("div", {}, up, el("button", {class: "btn", on: {click: async () => {
          if (!up.files[0]) return; m.ok("Importando...");
          try { const r2 = await api("/api/v1/mnt/atacado", {method: "POST", bytes: await up.files[0].arrayBuffer()}); m.ok(fmt.n(r2.cnpjs) + " CNPJs importados. O arquivo original não é mantido no servidor."); } catch (e) { m.er(e); } }}}, "Importar"),
          el("p", {class: "sub"}, "Dado sigiloso: visível apenas a usuários com permissão 'carteira'; CNPJs aparecem mascarados para não mantenedores.")));
    return [...titulo("Visão geral do sistema", r.edicao === "publica" ? "Edição pública (portal web)" : "Edição interna"),
      el("div", {class: "kpis"}, kpi(fmt.n(r.interessados), "Interessados cadastrados", fmt.n(r.interessados_7d) + " nos últimos 7 dias"), kpi(fmt.n(r.ativos), "Usuários ativos", fmt.n(r.usuarios) + " cadastrados"),
        kpi(fmt.n(r.sessoes), "Sessões ativas"), kpi(fmt.n(r.sac_abertos), "Chamados em aberto"), kpi(fmt.n(r.falhas_login_24h), "Falhas de login (24h)", fmt.n(r.sondagens_7d) + " tentativas em área restrita (7d)")),
      grade(
        cartao("Coleta e processamento", el("div", {},
          el("p", {class: "sub"}, "Executa as etapas marcadas e, em seguida, o cruzamento das bases e a estatística. O portal passa a exibir o resultado ao terminar."),
          el("div", {}, chk), el("p", {}, r.job.ativo ? "Em execução: " + r.job.etapa : ""),
          el("button", {class: "btn", on: {click: async () => { try { await api("/api/v1/mnt/coleta", {method: "POST", corpo: {etapas: chk.map((c) => c.firstChild).filter((i) => i.checked).map((i) => i.value)}}); m.ok("Processamento iniciado. Atualize esta tela para acompanhar."); } catch (e) { m.er(e); } }}}, "Executar"), " ",
          el("button", {class: "btn btn-sec", on: {click: async () => { await api("/api/v1/mnt/estatistica", {method: "POST"}); m.ok("Cruzamento e estatística reiniciados."); }}}, "Só cruzar e recalcular"), m)),
        cartao("Último cruzamento", it ? tabela([{item: "Processos identificados", n: it.processos}, {item: "…com ficha no DataJud", n: it.com_datajud}, {item: "…com edital de credores", n: it.com_edital},
          {item: "Partes identificadas", n: it.partes}, {item: "Grupos de devedoras", n: it.grupos}, {item: "Destinatários pessoa física (nome não gravado)", n: it.pf_nao_identificadas}], [["item", "Item"], ["n", "Quantidade"]]) : el("p", {class: "vazio"}, "Ainda não executado.")),
        base,
        cartao("Segurança", el("div", {}, el("p", {}, "Cadeia de auditoria: ", selo(r.cadeia_auditoria.integra ? "íntegra" : "ALTERADA", r.cadeia_auditoria.integra), ` (${r.cadeia_auditoria.verificados} registros)`),
          el("p", {}, "Integridade dos arquivos: ", r.integridade.verificado ? (r.integridade.alterados.length ? selo(r.integridade.alterados.length + " alterado(s)", false) : selo("conferida", true)) : selo("manifesto ausente", false)),
          r.integridade.alterados.length ? el("p", {class: "sub"}, r.integridade.alterados.join(", ")) : null,
          el("button", {class: "btn btn-perigo", on: {click: async () => { if (confirm("Encerrar a sessão de todos os outros usuários?")) { await api("/api/v1/mnt/sessoes/encerrar-todas", {method: "POST"}); abrir("mnt-resumo"); } }}}, "Encerrar todas as outras sessões"))),
        cartao("Últimas execuções", tabela(r.execucoes, [["etapa", "Etapa"], ["inicio", "Início", fmt.d], ["situacao", "Situação"], ["linhas", "Linhas"], ["nota", "Nota", null, "quebra"]]), null, {span: "s12"}))];
  });

  registrar("mnt-interessados", "Interessados (cadastro)", G, null, async () => {
    const d = await api("/api/v1/mnt/interessados"); const p = d.portal; const m = msg();
    const f = el("form", {class: "form-grade"},
      el("label", {class: "check", style: "grid-column:1/-1"}, el("input", {type: "checkbox", name: "exigir_cadastro", checked: p.exigir_cadastro}), "Exigir cadastro para o conteúdo completo do portal"),
      el("label", {}, "Validade do acesso no navegador (dias)", el("input", {name: "validade_cadastro_dias", type: "number", min: 1, max: 3650, value: p.validade_cadastro_dias})),
      el("label", {}, "Apagar cadastros sem acesso após (dias)", el("input", {name: "retencao_dias", type: "number", min: 30, max: 3650, value: p.retencao_dias})),
      el("label", {}, "Responsável pelos dados (exibido na página Privacidade)", el("input", {name: "controlador", maxlength: 200, value: p.controlador || ""})),
      el("label", {}, "E-mail para pedidos sobre dados pessoais", el("input", {name: "email_privacidade", type: "email", maxlength: 200, value: p.email_privacidade || ""})),
      el("div", {}, el("button", {class: "btn", type: "submit"}, "Salvar")), m);
    f.addEventListener("submit", async (ev) => { ev.preventDefault(); const o = Object.fromEntries(new FormData(f)); o.exigir_cadastro = f.exigir_cadastro.checked;
      try { await api("/api/v1/mnt/portal", {method: "POST", corpo: o}); m.ok("Configuração salva."); } catch (e) { m.er(e); } });
    return [...titulo("Interessados cadastrados no portal", "Dados pessoais – use apenas para as finalidades informadas na página Privacidade."), grade(
      cartao("Regras do portal", f, null, {span: "s7"}),
      cartao("Cadastros por perfil", tabela(d.perfis, [["perfil", "Perfil"], ["n", "Cadastros"]]), null, {span: "s5"}),
      cartao(`Cadastros (${fmt.n(d.lista.length)})`, el("div", {}, el("p", {}, el("a", {class: "btn btn-sec", href: "/api/v1/mnt/interessados/exportar"}, "Exportar CSV")),
        tabela(d.lista, [["nome", "Nome"], ["email", "E-mail"], ["organizacao", "Organização"], ["perfil", "Perfil"], ["interesse", "Interesse", null, "quebra"], ["novidades", "Avisos", (v) => v ? "sim" : ""],
          ["criado", "Cadastro", fmt.d], ["ultimo_acesso", "Último acesso", fmt.d], ["acessos", "Acessos"],
          ["id", "", (v) => el("button", {class: "btn-link", on: {click: async () => { if (confirm("Excluir este cadastro? (atende pedido de exclusão)")) { await api("/api/v1/mnt/interessados/" + v, {method: "DELETE"}); abrir("mnt-interessados"); } }}}, "excluir")]], 1000)), null, {span: "s12"}))];
  });

  registrar("mnt-usuarios", "Usuários", G, null, async () => {
    const us = await api("/api/v1/mnt/usuarios"); const m = msg();
    const PERMS = ["panorama", "macro", "credores", "carteira", "psi", "sac", "exportar"];
    const f = el("form", {class: "form-grade"}, el("input", {type: "hidden", name: "id"}),
      el("label", {}, "Login", el("input", {name: "login", maxlength: 40})), el("label", {}, "Nome", el("input", {name: "nome", maxlength: 120, required: true})),
      el("label", {}, "E-mail", el("input", {name: "email", type: "email", maxlength: 200, required: true})),
      el("label", {}, "Perfil", el("select", {name: "papel"}, ["usuario", "analista", "gestor"].map((p) => el("option", {}, p)))),
      el("label", {}, "Plano inicial", el("select", {name: "plano"}, ["basico", "analista", "corporativo"].map((p) => el("option", {}, p)))),
      el("label", {}, "Validade (dias)", el("input", {name: "dias", type: "number", value: 365, min: 1, max: 3650})),
      el("label", {}, "Ativo", el("select", {name: "ativo"}, el("option", {value: "1"}, "sim"), el("option", {value: "0"}, "não"))),
      el("div", {style: "grid-column:1/-1"}, el("strong", {}, "Permissões adicionais"), el("div", {}, PERMS.map((p) => el("label", {class: "check", style: "display:inline-flex;margin-right:10px"}, el("input", {type: "checkbox", name: "perm", value: p}), p)))),
      el("div", {}, el("button", {class: "btn", type: "submit"}, "Salvar"), " ", el("button", {type: "reset", class: "btn btn-sec"}, "Novo")), m);
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault(); const fd = new FormData(f); const o = Object.fromEntries(fd); o.permissoes = fd.getAll("perm"); o.ativo = o.ativo === "1"; delete o.perm; if (!o.id) delete o.id;
      try { const r = await api("/api/v1/mnt/usuarios", {method: "POST", corpo: o}); m.ok(r.senha_temporaria ? `Usuário criado. Senha temporária: ${r.senha_temporaria} — ${r.aviso}` : "Alterações salvas."); } catch (e) { m.er(e); }
    });
    const editar = (u) => { f.elements.id.value = u.id; f.elements.login.value = u.login; f.elements.login.disabled = true; f.elements.nome.value = u.nome; f.elements.email.value = u.email; f.elements.papel.value = u.papel; f.elements.ativo.value = u.ativo ? "1" : "0";
      const p = JSON.parse(u.permissoes || "[]"); f.querySelectorAll("[name=perm]").forEach((c) => { c.checked = p.includes(c.value); }); };
    f.addEventListener("reset", () => { f.elements.login.disabled = false; });
    return [...titulo("Usuários e permissões"), grade(cartao("Cadastro", f, null, {span: "s5"}), cartao("Usuários", tabela(us, [["login", "Login"], ["nome", "Nome"], ["papel", "Perfil"],
      ["ativo", "Ativo", (v) => selo(v ? "ativo" : "inativo", v)], ["dois_fatores", "2FA", (v) => v ? "sim" : "não"], ["assinatura", "Assinatura", (v) => (v || "").split("|")[0]], ["ultimo_acesso", "Último acesso", fmt.d],
      ["id", "", (v, u) => u.papel === "mantenedor" ? "" : el("span", {}, el("button", {class: "btn-link", on: {click: () => editar(u)}}, "editar"), " ",
        el("button", {class: "btn-link", on: {click: async () => { if (confirm("Redefinir senha e 2FA deste usuário?")) { const r = await api(`/api/v1/mnt/usuarios/${v}/redefinir`, {method: "POST"}); alert("Senha temporária: " + r.senha_temporaria); } }}}, "redefinir"))]]), null, {span: "s7"}))];
  });

  registrar("mnt-assinaturas", "Assinaturas", G, null, async () => {
    const d = await api("/api/v1/mnt/assinaturas"); const m = msg();
    const f = el("form", {class: "form-grade"}, el("input", {type: "hidden", name: "id"}), el("label", {}, "Login do usuário", el("input", {name: "login"})),
      el("label", {}, "Plano", el("select", {name: "plano"}, d.planos.map((p) => el("option", {value: p.codigo}, p.nome)))), el("label", {}, "Validade a partir de hoje (dias)", el("input", {name: "dias", type: "number", value: 365})),
      el("label", {}, "Situação", el("select", {name: "situacao"}, ["ativa", "suspensa", "cancelada"].map((s) => el("option", {}, s)))), el("label", {}, "Observação", el("input", {name: "obs", maxlength: 300})),
      el("div", {}, el("button", {class: "btn", type: "submit"}, "Salvar")), m);
    f.addEventListener("submit", async (ev) => { ev.preventDefault(); const o = Object.fromEntries(new FormData(f)); if (!o.id) delete o.id; try { await api("/api/v1/mnt/assinaturas", {method: "POST", corpo: o}); abrir("mnt-assinaturas"); } catch (e) { m.er(e); } });
    return [...titulo("Planos e assinaturas da área restrita", "Integração com meio de pagamento poderá ser conectada quando houver domínio"), grade(
      cartao("Planos", tabela(d.planos, [["nome", "Plano"], ["recursos", "Recursos", (v) => JSON.parse(v).join(", ")]])), cartao("Nova / alterar assinatura", f),
      cartao("Assinaturas", tabela(d.assinaturas, [["login", "Login"], ["plano", "Plano"], ["fim", "Vence em", fmt.d], ["situacao", "Situação"], ["obs", "Obs."],
        ["id", "", (v, a) => el("button", {class: "btn-link", on: {click: () => { f.elements.id.value = v; f.elements.login.value = a.login; f.elements.plano.value = a.plano; f.elements.situacao.value = a.situacao; f.elements.obs.value = a.obs || ""; }}}, "editar")]]), null, {span: "s12"}))];
  });

  registrar("mnt-auditoria", "Auditoria", G, null, async () => {
    const box = el("div"); const filtro = el("input", {placeholder: "filtrar por ação (ex.: login, exportacao, cadastro_portal, sondagem)"});
    const carregar = async () => { const d = await api("/api/v1/mnt/auditoria?acao=" + encodeURIComponent(filtro.value));
      box.replaceChildren(el("p", {}, "Cadeia de registros: ", selo(d.cadeia.integra ? "íntegra" : "ALTERADA no registro " + d.cadeia.registro_divergente, d.cadeia.integra)),
        tabela(d.registros, [["quando", "Quando", fmt.d], ["login", "Usuário"], ["ip", "IP"], ["acao", "Ação"], ["detalhe", "Detalhe", null, "quebra"]], 500)); };
    filtro.addEventListener("change", carregar); await carregar();
    return [...titulo("Trilha de auditoria", "Registros encadeados por hash: qualquer alteração posterior é detectada"), grade(cartao("Filtro", filtro, null, {span: "s12"}), cartao("Registros", box, null, {span: "s12"}))];
  });

  registrar("mnt-sac", "Atendimento (SAC)", G, null, async () => {
    const lst = await api("/api/v1/mnt/sac"); const det = el("div");
    const ver = async (id) => {
      const d = await api("/api/v1/mnt/sac/" + id); const t = el("textarea", {rows: 3, maxlength: 4000}); const sit = el("select", {}, ["em atendimento", "respondido", "encerrado", "aberto"].map((s) => el("option", {}, s)));
      const interno = el("input", {type: "checkbox"});
      det.replaceChildren(grade(cartao(`${d.chamado.protocolo} – ${d.chamado.assunto}`, el("div", {}, el("p", {}, `${d.chamado.nome} · ${d.chamado.email} · ${d.chamado.categoria}`),
        el("div", {class: "chat"}, d.mensagens.map((x) => el("div", {class: "m " + (x.interno ? "interno" : x.autor)}, el("div", {class: "q"}, (x.interno ? "Nota interna" : x.autor) + " · " + fmt.d(x.quando)), x.texto))),
        el("label", {}, "Resposta", t), el("label", {class: "check"}, interno, "nota interna (não visível ao cliente)"), el("label", {}, "Situação", sit),
        el("button", {class: "btn", on: {click: async () => { await api("/api/v1/mnt/sac/" + id, {method: "POST", corpo: {texto: t.value, interno: interno.checked, situacao: sit.value}}); ver(id); }}}, "Registrar")), null, {span: "s12"})));
    };
    return [...titulo("Atendimento ao cliente"), el("div", {class: "info"}, "Pedidos de exclusão de dados pessoais chegam por aqui: exclua o cadastro em 'Interessados' e registre a resposta."),
      grade(cartao("Chamados", tabela(lst, [["protocolo", "Protocolo"], ["nome", "Cliente"], ["assunto", "Assunto", null, "quebra"], ["categoria", "Categoria"], ["situacao", "Situação"], ["atualizado", "Atualizado", fmt.d],
        ["id", "", (v) => el("button", {class: "btn-link", on: {click: () => ver(v)}}, "abrir")]]), null, {span: "s12"})), det];
  });

  registrar("mnt-rede", "Rede e fontes", G, null, async () => {
    const box = el("div", {}, el("p", {class: "vazio"}, "Clique em diagnosticar."));
    const f = el("form", {}, el("label", {}, "Proxy corporativo (http://servidor:porta – sem usuário/senha)", el("input", {name: "proxy"})),
      el("label", {}, "Certificado raiz corporativo (caminho do arquivo .pem/.cer no servidor)", el("input", {name: "ca_bundle"})), el("button", {class: "btn", type: "submit"}, "Salvar"));
    const m = msg();
    f.addEventListener("submit", async (ev) => { ev.preventDefault(); try { await api("/api/v1/mnt/rede", {method: "POST", corpo: Object.fromEntries(new FormData(f))}); m.ok("Configuração salva."); } catch (e) { m.er(e); } });
    const diag = async () => { box.replaceChildren(el("p", {}, "Testando rotas e fontes (até 2 minutos)...")); const d = await api("/api/v1/mnt/rede");
      box.replaceChildren(el("p", {}, "Rota escolhida: ", el("strong", {}, d.rota_escolhida)), tabela(d.rotas, [["rota", "Rota"], ["resultado", "Resultado", null, "quebra"]]), el("br"),
        tabela(d.fontes, [["fonte", "Fonte"], ["status", "HTTP"], ["resultado", "Resultado", null, "quebra"]])); };
    return [...titulo("Rede e fontes de dados", "Senha do proxy só por variável de ambiente (MOTOR_PROXY_USER / MOTOR_PROXY_PASS) – nunca gravada"),
      grade(cartao("Diagnóstico", el("div", {}, el("button", {class: "btn", on: {click: diag}}, "Diagnosticar"), box), null, {span: "s7"}), cartao("Configuração", el("div", {}, f, m), null, {span: "s5"}))];
  });
})();
