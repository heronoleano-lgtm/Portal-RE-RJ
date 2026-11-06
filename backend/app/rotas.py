"""Rotas da API (autenticação, área do usuário, painéis restritos, PSI, SAC).
Portal público e cadastro: rotas_publicas.py · Administração: rotas_mantenedor.py"""
import csv, io, json, re, secrets, time
from .servidor import rota, COOKIE
from .config import CFG, PUBLICA, RECURSOS_RESTRITOS
from . import db, seguranca as S
from .seguranca import ErroUsuario, texto

RECURSOS_TODOS = ["panorama", "macro", "credores", "carteira", "psi", "sac", "exportar"]


def _recursos(u):
    if u["papel"] == "mantenedor":
        return RECURSOS_TODOS
    extra = json.loads(u.get("permissoes") or "[]")
    with db.sis() as c:
        a = c.execute("""SELECT p.recursos FROM assinaturas a JOIN planos p ON p.codigo=a.plano
                         WHERE a.usuario_id=? AND a.situacao='ativa' AND (a.fim IS NULL OR a.fim>?) ORDER BY a.fim DESC LIMIT 1""",
                      (u["id"], time.time())).fetchone()
    base = json.loads(a["recursos"]) if a else ["sac"]
    return sorted(set(base) | set(extra))


def recursos(u):
    return [r for r in _recursos(u) if not (PUBLICA and r in RECURSOS_RESTRITOS)]


def exige(ctx, recurso):
    if PUBLICA and recurso in RECURSOS_RESTRITOS:
        raise ErroUsuario("Conteúdo não disponível.")
    if recurso not in recursos(ctx.usuario):
        raise ErroUsuario("Seu plano não inclui este conteúdo. Fale com o suporte para ampliar o acesso.")


def publico_usuario(u):
    return {"login": u["login"], "nome": u["nome"], "email": u["email"], "papel": "mantenedor" if u["papel"] == "mantenedor" else "usuario",
            "dois_fatores": bool(u["totp"]), "trocar_senha": bool(u["trocar_senha"])}


def _criar_sessao(h, u, ip):
    tok = S.novo_token(); csrf = secrets.token_urlsafe(24); agora = time.time()
    with db.sis() as c:
        c.execute("INSERT INTO sessoes VALUES(?,?,?,?,?,?,?,?)", (S.h256(tok), u["id"], csrf, agora, agora,
                  agora + CFG["servidor"]["sessao_horas"] * 3600, ip, (h.headers.get("User-Agent") or "")[:200]))
        c.execute("UPDATE usuarios SET falhas=0, bloqueado_ate=0, ultimo_acesso=? WHERE id=?", (agora, u["id"]))
    seguro = "; Secure" if CFG["servidor"]["https_atras_de_proxy_reverso"] else ""
    return csrf, f"{COOKIE}={tok}; HttpOnly; SameSite=Strict; Path=/{seguro}; Max-Age={CFG['servidor']['sessao_horas'] * 3600}"


# ---------------- autenticação ----------------
@rota("POST", "/api/entrar", "publico")
def entrar(ctx):
    ip = ctx.ip; login = (ctx.corpo.get("login") or "").strip().lower()[:40]; senha = ctx.corpo.get("senha") or ""
    codigo = re.sub(r"\D", "", str(ctx.corpo.get("codigo") or ""))[:8]; recup = (ctx.corpo.get("recuperacao") or "").strip()[:20]
    generico = "Usuário ou senha inválidos."
    if not S.LOGIN_IP.permitido(ip) or not S.LOGIN_CONTA.permitido(login):
        db.auditar("login_bloqueado_limite", None, ip, {"login": login})
        raise ErroUsuario("Muitas tentativas. Aguarde 15 minutos.")
    with db.sis() as c:
        u = c.execute("SELECT * FROM usuarios WHERE login=? AND ativo=1", (login,)).fetchone()
    if not u:
        S.atraso_uniforme(senha); S.LOGIN_IP.registra(ip); S.LOGIN_CONTA.registra(login)
        db.auditar("login_falha", None, ip, {"login": login}); raise ErroUsuario(generico)
    u = dict(u)
    if u["bloqueado_ate"] > time.time():
        raise ErroUsuario("Conta temporariamente bloqueada. Tente mais tarde.")
    if not S.confere_senha(senha, u["senha"]):
        S.LOGIN_IP.registra(ip); S.LOGIN_CONTA.registra(login)
        with db.sis() as c:
            f = u["falhas"] + 1
            c.execute("UPDATE usuarios SET falhas=?, bloqueado_ate=? WHERE id=?", (f, time.time() + 900 if f >= 8 else 0, u["id"]))
        db.auditar("login_falha", u, ip); raise ErroUsuario(generico)
    if u["totp"] or u["papel"] == "mantenedor":
        ok = False
        if codigo and u["totp"]:
            ok = S.confere_totp(u["totp"], codigo)
        elif recup:
            with db.sis() as c:
                r = c.execute("SELECT rowid FROM recuperacao WHERE usuario_id=? AND hash=? AND usado=0", (u["id"], S.h256(recup.upper()))).fetchone()
                if r:
                    c.execute("UPDATE recuperacao SET usado=1 WHERE rowid=?", (r[0],)); ok = True
                    db.auditar("codigo_recuperacao_usado", u, ip)
        if not ok:
            if codigo or recup:
                S.LOGIN_IP.registra(ip); db.auditar("login_falha_2fa", u, ip)
                raise ErroUsuario("Código de verificação inválido.")
            return ctx.h.json({"precisa_2fa": True})
    S.LOGIN_CONTA.limpa(login)
    csrf, ck = _criar_sessao(ctx.h, u, ip)
    db.auditar("login_ok", u, ip)
    return ctx.h.json({"ok": True, "csrf": csrf, "usuario": publico_usuario(u), "recursos": recursos(u)}, extra={"Set-Cookie": ck})


@rota("GET", "/api/sessao", "publico")
def sessao(ctx):
    base = {"cadastro_exigido": bool(CFG["portal"].get("exigir_cadastro", True)), "liberado": ctx.liberado,
            "visitante": ctx.visitante["nome"].split(" ")[0] if ctx.visitante else None}
    if not ctx.usuario:
        return ctx.h.json(dict(base, autenticado=False, portal=PUBLICA))
    return ctx.h.json(dict(base, autenticado=True, csrf=ctx.sessao["csrf"], usuario=publico_usuario(ctx.usuario), recursos=recursos(ctx.usuario)))


@rota("POST", "/api/sair")
def sair(ctx):
    with db.sis() as c:
        c.execute("DELETE FROM sessoes WHERE token_h=?", (ctx.sessao["token_h"],))
    db.auditar("logout", ctx.usuario, ctx.ip)
    return ctx.h.json({"ok": True}, extra={"Set-Cookie": f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})


# ---------------- área do usuário ----------------
@rota("POST", "/api/conta/senha")
def trocar_senha(ctx):
    atual, nova = ctx.corpo.get("atual") or "", ctx.corpo.get("nova") or ""
    if not S.confere_senha(atual, ctx.usuario["senha"]):
        raise ErroUsuario("Senha atual incorreta.")
    erro = S.politica_senha(nova)
    if erro:
        raise ErroUsuario(erro)
    with db.sis() as c:
        c.execute("UPDATE usuarios SET senha=?, trocar_senha=0 WHERE id=?", (S.hash_senha(nova), ctx.usuario["id"]))
        c.execute("DELETE FROM sessoes WHERE usuario_id=? AND token_h<>?", (ctx.usuario["id"], ctx.sessao["token_h"]))
    db.auditar("senha_alterada", ctx.usuario, ctx.ip)
    return ctx.h.json({"ok": True, "mensagem": "Senha alterada. Outras sessões foram encerradas."})


_TOTP_PEND = {}


@rota("POST", "/api/conta/2fa/iniciar")
def tfa_iniciar(ctx):
    seg = S.novo_segredo_totp(); _TOTP_PEND[ctx.usuario["id"]] = (seg, time.time())
    return ctx.h.json({"segredo": seg, "uri": S.uri_totp(seg, ctx.usuario["login"])})


@rota("POST", "/api/conta/2fa/confirmar")
def tfa_confirmar(ctx):
    seg, t = _TOTP_PEND.get(ctx.usuario["id"], (None, 0))
    if not seg or time.time() - t > 600 or not S.confere_totp(seg, str(ctx.corpo.get("codigo") or "")):
        raise ErroUsuario("Código inválido ou expirado. Gere um novo segredo.")
    codigos = [secrets.token_hex(4).upper() for _ in range(8)]
    with db.sis() as c:
        c.execute("UPDATE usuarios SET totp=? WHERE id=?", (seg, ctx.usuario["id"]))
        c.execute("DELETE FROM recuperacao WHERE usuario_id=?", (ctx.usuario["id"],))
        c.executemany("INSERT INTO recuperacao(usuario_id,hash) VALUES(?,?)", [(ctx.usuario["id"], S.h256(k)) for k in codigos])
    _TOTP_PEND.pop(ctx.usuario["id"], None); db.auditar("2fa_ativado", ctx.usuario, ctx.ip)
    return ctx.h.json({"ok": True, "codigos_recuperacao": codigos})


@rota("GET", "/api/conta/sessoes")
def minhas_sessoes(ctx):
    with db.sis() as c:
        rs = c.execute("SELECT token_h, criado, visto, ip, agente FROM sessoes WHERE usuario_id=? ORDER BY visto DESC", (ctx.usuario["id"],)).fetchall()
    return ctx.h.json([{"id": r["token_h"][:12], "atual": r["token_h"] == ctx.sessao["token_h"], "criado": r["criado"], "visto": r["visto"],
                        "ip": r["ip"], "navegador": r["agente"][:80]} for r in rs])


@rota("POST", "/api/conta/sessoes/encerrar")
def encerrar_sessoes(ctx):
    with db.sis() as c:
        c.execute("DELETE FROM sessoes WHERE usuario_id=? AND token_h<>?", (ctx.usuario["id"], ctx.sessao["token_h"]))
    db.auditar("sessoes_encerradas", ctx.usuario, ctx.ip)
    return ctx.h.json({"ok": True})


@rota("GET", "/api/conta/assinatura")
def minha_assinatura(ctx):
    with db.sis() as c:
        a = c.execute("""SELECT p.nome plano, a.inicio, a.fim, a.situacao FROM assinaturas a JOIN planos p ON p.codigo=a.plano
                         WHERE a.usuario_id=? ORDER BY a.id DESC LIMIT 1""", (ctx.usuario["id"],)).fetchone()
    return ctx.h.json({"assinatura": dict(a) if a else None, "recursos": recursos(ctx.usuario)})


# ---------------- painéis restritos ----------------
@rota("GET", "/api/painel/carteira")
def painel_carteira(ctx):
    exige(ctx, "carteira")
    g = db.estat_get
    vig = g("carteira_vigilancia") or []
    if ctx.usuario["papel"] != "mantenedor":
        vig = [dict(v, cnpj=S.mascara_cnpj(v["cnpj"])) for v in vig]
    db.auditar("acesso_carteira", ctx.usuario, ctx.ip)
    return ctx.h.json({"resumo": g("carteira_resumo"), "taxas": g("carteira_taxas"), "foco_setor": g("carteira_foco_setor"),
                       "grupos": g("carteira_grupos"), "logit": g("carteira_logit"), "vigilancia": vig, "processos": g("carteira_processos")})


@rota("GET", "/api/exportar/(credores|vigilancia|processos)")
def exportar(ctx, qual):
    exige(ctx, "exportar")
    if qual == "vigilancia":
        exige(ctx, "carteira")
        linhas = db.estat_get("carteira_vigilancia") or []
        if ctx.usuario["papel"] != "mantenedor":
            linhas = [dict(v, cnpj=S.mascara_cnpj(v["cnpj"])) for v in linhas]
    elif qual == "processos":
        linhas = (db.estat_get("processos") or {}).get("lista", [])
    else:
        exige(ctx, "credores"); linhas = (db.estat_get("credores") or {}).get("processos", [])
        if PUBLICA:
            linhas = [{k: v for k, v in l.items() if k not in ("cliente_atacado", "caixa", "caixa_%")} for l in linhas]
    buf = io.StringIO()
    if linhas:
        w = csv.DictWriter(buf, fieldnames=list(linhas[0].keys()), delimiter=";"); w.writeheader()
        for l in linhas:
            w.writerow({k: S.csv_seguro(v) for k, v in l.items()})
    b = ("\ufeff" + buf.getvalue()).encode("utf-8")
    db.auditar("exportacao", ctx.usuario, ctx.ip, {"conjunto": qual, "linhas": len(linhas)})
    ctx.h._cab(200, "text/csv; charset=utf-8", len(b), {"Content-Disposition": f'attachment; filename="{qual}.csv"', "Cache-Control": "no-store"})
    ctx.h.wfile.write(b)


# ---------------- PSI 15508 ----------------
PSI_TAB = {"casos": ("psi_casos", ["identificacao", "setor", "uf", "data_concessao", "data_pedido_rj", "modalidade", "valor_mil", "garantias", "rating", "premissas", "evidencia"]),
           "indicadores": ("psi_indicadores", ["caso_id", "indicador", "v_concessao", "v_pre_rj", "considerado", "evidencia"]),
           "fatores": ("psi_fatores", ["caso_id", "fator", "categoria", "presente", "tratamento", "impacto", "evidencia"]),
           "recomendacoes": ("psi_recomendacoes", ["recomendacao", "processo", "impacto", "aplicabilidade", "casos", "status"])}


@rota("GET", "/api/psi/(casos|indicadores|fatores|recomendacoes)")
def psi_listar(ctx, t):
    exige(ctx, "psi"); tab, _ = PSI_TAB[t]
    with db.ana() as c:
        return ctx.h.json([dict(r) for r in c.execute(f"SELECT * FROM {tab} ORDER BY id")])


@rota("POST", "/api/psi/(casos|indicadores|fatores|recomendacoes)")
def psi_salvar(ctx, t):
    exige(ctx, "psi"); tab, cols = PSI_TAB[t]
    vals = []
    for col in cols:
        v = ctx.corpo.get(col)
        if col in ("valor_mil", "v_concessao", "v_pre_rj"):
            v = float(str(v).replace(",", ".")) if v not in (None, "") and re.fullmatch(r"-?\d+([.,]\d+)?", str(v)) else None
        elif col in ("caso_id", "impacto", "aplicabilidade"):
            v = int(v) if str(v or "").isdigit() else None
        else:
            v = texto(v, 4000, obrig=False)
        vals.append(v)
    if "evidencia" in cols and not vals[cols.index("evidencia")]:
        raise ErroUsuario("Informe a evidência (documento e página) – exigência da orientação do PSI.")
    with db.ana() as c:
        rid = ctx.corpo.get("id")
        if rid:
            c.execute(f"UPDATE {tab} SET {','.join(col + '=?' for col in cols)} WHERE id=?", vals + [int(rid)])
        else:
            rid = c.execute(f"INSERT INTO {tab}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals).lastrowid
    db.auditar("psi_registro", ctx.usuario, ctx.ip, {"tabela": t, "id": rid})
    return ctx.h.json({"ok": True, "id": rid})


@rota("DELETE", r"/api/psi/(casos|indicadores|fatores|recomendacoes)/(\d+)")
def psi_excluir(ctx, t, rid):
    exige(ctx, "psi")
    with db.ana() as c:
        c.execute(f"DELETE FROM {PSI_TAB[t][0]} WHERE id=?", (int(rid),))
    db.auditar("psi_exclusao", ctx.usuario, ctx.ip, {"tabela": t, "id": rid})
    return ctx.h.json({"ok": True})


# ---------------- SAC ----------------
def _protocolo():
    return time.strftime("%Y%m%d") + "-" + secrets.token_hex(3).upper()


def novo_chamado(uid, nome, email, assunto, categoria, msg):
    p = _protocolo(); agora = time.time()
    with db.sis() as c:
        cid = c.execute("INSERT INTO sac_chamados(protocolo,usuario_id,nome,email,assunto,categoria,criado,atualizado) VALUES(?,?,?,?,?,?,?,?)",
                        (p, uid, nome, email, assunto, categoria, agora, agora)).lastrowid
        c.execute("INSERT INTO sac_mensagens(chamado_id,autor,texto,quando) VALUES(?,?,?,?)", (cid, "cliente", msg, agora))
    return p


@rota("POST", "/api/sac/contato", "publico")
def sac_publico(ctx):
    if not S.SAC_IP.permitido(ctx.ip):
        raise ErroUsuario("Limite de contatos atingido. Tente novamente mais tarde.")
    if ctx.corpo.get("site"):  # campo-isca anti-robô
        return ctx.h.json({"ok": True, "protocolo": _protocolo()})
    nome = texto(ctx.corpo.get("nome"), 120); email = texto(ctx.corpo.get("email"), 200)
    if not S.RX_EMAIL.match(email):
        raise ErroUsuario("Informe um e-mail válido.")
    assunto = texto(ctx.corpo.get("assunto"), 160); msg = texto(ctx.corpo.get("mensagem"), 4000)
    S.SAC_IP.registra(ctx.ip)
    return ctx.h.json({"ok": True, "protocolo": novo_chamado(None, nome, email, assunto, "Contato", msg)})


@rota("POST", "/api/sac/chamados")
def sac_novo(ctx):
    cat = ctx.corpo.get("categoria") if ctx.corpo.get("categoria") in ("Dúvida", "Problema técnico", "Acesso e assinatura", "Sugestão", "Dados") else "Dúvida"
    p = novo_chamado(ctx.usuario["id"], ctx.usuario["nome"], ctx.usuario["email"], texto(ctx.corpo.get("assunto"), 160), cat, texto(ctx.corpo.get("mensagem"), 4000))
    db.auditar("sac_aberto", ctx.usuario, ctx.ip, {"protocolo": p})
    return ctx.h.json({"ok": True, "protocolo": p})


@rota("GET", "/api/sac/chamados")
def sac_meus(ctx):
    with db.sis() as c:
        rs = c.execute("SELECT id, protocolo, assunto, categoria, situacao, criado, atualizado FROM sac_chamados WHERE usuario_id=? ORDER BY atualizado DESC", (ctx.usuario["id"],)).fetchall()
    return ctx.h.json([dict(r) for r in rs])


@rota("GET", r"/api/sac/chamados/(\d+)")
def sac_ver(ctx, cid):
    with db.sis() as c:
        ch = c.execute("SELECT * FROM sac_chamados WHERE id=? AND usuario_id=?", (int(cid), ctx.usuario["id"])).fetchone()
        if not ch:
            return ctx.h.nao_encontrado()
        ms = c.execute("SELECT autor, texto, quando FROM sac_mensagens WHERE chamado_id=? AND interno=0 ORDER BY id", (int(cid),)).fetchall()
    return ctx.h.json({"chamado": {k: ch[k] for k in ("protocolo", "assunto", "categoria", "situacao", "criado")}, "mensagens": [dict(m) for m in ms]})


@rota("POST", r"/api/sac/chamados/(\d+)/mensagem")
def sac_responder(ctx, cid):
    with db.sis() as c:
        ch = c.execute("SELECT id FROM sac_chamados WHERE id=? AND usuario_id=?", (int(cid), ctx.usuario["id"])).fetchone()
        if not ch:
            return ctx.h.nao_encontrado()
        c.execute("INSERT INTO sac_mensagens(chamado_id,autor,texto,quando) VALUES(?,?,?,?)", (int(cid), "cliente", texto(ctx.corpo.get("texto"), 4000), time.time()))
        c.execute("UPDATE sac_chamados SET situacao='aberto', atualizado=? WHERE id=?", (time.time(), int(cid)))
    return ctx.h.json({"ok": True})


from . import rotas_mantenedor, rotas_publicas  # noqa: E402,F401
