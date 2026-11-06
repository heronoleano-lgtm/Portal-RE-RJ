"""Rotas exclusivas do mantenedor (/api/mnt/*). Para qualquer outro perfil respondem 404 e a tentativa é auditada."""
import csv, io, json, os, re, secrets, tempfile, threading, time
from .servidor import rota, verificar_integridade
from .config import CFG, DIR_DADOS, salvar_parcial, PUBLICA
from . import db, seguranca as S, estatistica, atacado, rede
from .pipeline import processar_tudo
from .seguranca import ErroUsuario, texto
from .coleta import fontes

_JOB = {"ativo": False, "etapa": None}


@rota("GET", "/api/mnt/resumo", "mantenedor")
def resumo(ctx):
    agora = time.time()
    with db.sis() as c:
        u = c.execute("SELECT COUNT(*) n, SUM(ativo) ativos FROM usuarios").fetchone()
        s = c.execute("SELECT COUNT(*) FROM sessoes WHERE expira>?", (agora,)).fetchone()[0]
        sac = c.execute("SELECT COUNT(*) FROM sac_chamados WHERE situacao<>'encerrado'").fetchone()[0]
        falhas = c.execute("SELECT COUNT(*) FROM auditoria WHERE acao LIKE 'login_falha%' AND quando>?", (agora - 86400,)).fetchone()[0]
        sond = c.execute("SELECT COUNT(*) FROM auditoria WHERE acao='sondagem_area_restrita' AND quando>?", (agora - 7 * 86400,)).fetchone()[0]
        intr = c.execute("SELECT COUNT(*), SUM(criado>?) FROM interessados", (agora - 7 * 86400,)).fetchone()
    with db.ana() as c:
        ex = [dict(r) for r in c.execute("SELECT etapa, inicio, fim, situacao, linhas, nota FROM coleta_execucoes ORDER BY id DESC LIMIT 20")]
    return ctx.h.json({"edicao": "publica" if PUBLICA else "interna", "usuarios": u["n"], "ativos": u["ativos"] or 0, "sessoes": s, "sac_abertos": sac,
                       "falhas_login_24h": falhas, "sondagens_7d": sond, "interessados": intr[0], "interessados_7d": intr[1] or 0,
                       "job": _JOB, "execucoes": ex, "etapas": list(fontes.ETAPAS), "padrao": fontes.PADRAO_COLETA,
                       "integracao": db.estat_get("integracao"), "integridade": verificar_integridade(), "cadeia_auditoria": db.verificar_cadeia()})


# ---------- interessados (cadastro do portal) ----------
@rota("GET", "/api/mnt/interessados", "mantenedor")
def interessados(ctx):
    with db.sis() as c:
        rs = [dict(r) for r in c.execute("""SELECT id, nome, email, organizacao, perfil, interesse, novidades, criado, ultimo_acesso, acessos
                                           FROM interessados ORDER BY criado DESC LIMIT 1000""")]
        perfis = [dict(r) for r in c.execute("SELECT perfil, COUNT(*) n FROM interessados GROUP BY perfil ORDER BY n DESC")]
    return ctx.h.json({"lista": rs, "perfis": perfis, "portal": CFG["portal"]})


@rota("GET", "/api/mnt/interessados/exportar", "mantenedor")
def interessados_csv(ctx):
    with db.sis() as c:
        rs = [dict(r) for r in c.execute("SELECT nome, email, organizacao, perfil, interesse, novidades, criado, ultimo_acesso FROM interessados ORDER BY criado")]
    buf = io.StringIO()
    if rs:
        w = csv.DictWriter(buf, fieldnames=list(rs[0].keys()), delimiter=";"); w.writeheader()
        for r in rs:
            r["criado"] = time.strftime("%d/%m/%Y %H:%M", time.localtime(r["criado"] or 0))
            r["ultimo_acesso"] = time.strftime("%d/%m/%Y %H:%M", time.localtime(r["ultimo_acesso"] or 0))
            w.writerow({k: S.csv_seguro(v) for k, v in r.items()})
    b = ("\ufeff" + buf.getvalue()).encode("utf-8")
    db.auditar("interessados_exportados", ctx.usuario, ctx.ip, {"linhas": len(rs)})
    ctx.h._cab(200, "text/csv; charset=utf-8", len(b), {"Content-Disposition": 'attachment; filename="interessados.csv"', "Cache-Control": "no-store"})
    ctx.h.wfile.write(b)


@rota("DELETE", r"/api/mnt/interessados/(\d+)", "mantenedor")
def interessado_excluir(ctx, iid):
    with db.sis() as c:
        c.execute("DELETE FROM interessados WHERE id=?", (int(iid),))
    db.auditar("interessado_excluido", ctx.usuario, ctx.ip, {"id": iid})
    return ctx.h.json({"ok": True})


@rota("POST", "/api/mnt/portal", "mantenedor")
def portal_config(ctx):
    b = ctx.corpo; p = dict(CFG["portal"])
    p["exigir_cadastro"] = bool(b.get("exigir_cadastro"))
    for k, lo, hi in (("validade_cadastro_dias", 1, 3650), ("retencao_dias", 30, 3650)):
        try:
            p[k] = max(lo, min(int(b.get(k, p[k])), hi))
        except (TypeError, ValueError):
            raise ErroUsuario("Prazo inválido.")
    p["controlador"] = texto(b.get("controlador"), 200, obrig=False)
    em = texto(b.get("email_privacidade"), 200, obrig=False)
    if em and not S.RX_EMAIL.match(em):
        raise ErroUsuario("E-mail de privacidade inválido.")
    p["email_privacidade"] = em
    CFG["portal"] = p; salvar_parcial("portal", p)
    from . import rotas_publicas
    rotas_publicas._CACHE["chave"] = None
    db.auditar("portal_configurado", ctx.usuario, ctx.ip, {k: p[k] for k in ("exigir_cadastro", "validade_cadastro_dias", "retencao_dias")})
    return ctx.h.json({"ok": True, "portal": p})


# ---------- usuários ----------
@rota("GET", "/api/mnt/usuarios", "mantenedor")
def usuarios(ctx):
    with db.sis() as c:
        rs = c.execute("""SELECT u.id, u.login, u.nome, u.email, u.papel, u.ativo, u.permissoes, u.totp IS NOT NULL dois_fatores, u.ultimo_acesso,
               u.bloqueado_ate, (SELECT plano||'|'||IFNULL(fim,'')||'|'||situacao FROM assinaturas a WHERE a.usuario_id=u.id ORDER BY a.id DESC LIMIT 1) assinatura
               FROM usuarios u ORDER BY u.id""").fetchall()
    return ctx.h.json([dict(r) for r in rs])


@rota("POST", "/api/mnt/usuarios", "mantenedor")
def usuario_salvar(ctx):
    b = ctx.corpo; papel = b.get("papel") if b.get("papel") in ("usuario", "analista", "gestor") else "usuario"
    perms = [p for p in (b.get("permissoes") or []) if p in ("panorama", "macro", "credores", "carteira", "psi", "sac", "exportar")]
    with db.sis() as c:
        if b.get("id"):
            alvo = c.execute("SELECT * FROM usuarios WHERE id=?", (int(b["id"]),)).fetchone()
            if not alvo or alvo["papel"] == "mantenedor":
                raise ErroUsuario("Usuário não pode ser alterado por esta tela.")
            c.execute("UPDATE usuarios SET nome=?, email=?, papel=?, ativo=?, permissoes=? WHERE id=?",
                      (texto(b.get("nome"), 120), texto(b.get("email"), 200), papel, 1 if b.get("ativo", True) else 0, json.dumps(perms), int(b["id"])))
            if not b.get("ativo", True):
                c.execute("DELETE FROM sessoes WHERE usuario_id=?", (int(b["id"]),))
            db.auditar("usuario_alterado", ctx.usuario, ctx.ip, {"id": b["id"], "papel": papel, "permissoes": perms, "ativo": b.get("ativo", True)})
            return ctx.h.json({"ok": True})
        login = (b.get("login") or "").strip().lower()
        if not S.RX_LOGIN.match(login):
            raise ErroUsuario("Login: 3 a 40 caracteres (letras minúsculas, números, ponto, hífen).")
        email = texto(b.get("email"), 200)
        if not S.RX_EMAIL.match(email):
            raise ErroUsuario("E-mail inválido.")
        temp = secrets.token_urlsafe(9) + "!a1"
        try:
            uid = c.execute("INSERT INTO usuarios(login,nome,email,senha,papel,trocar_senha,permissoes,criado) VALUES(?,?,?,?,?,1,?,?)",
                            (login, texto(b.get("nome"), 120), email, S.hash_senha(temp), papel, json.dumps(perms), time.time())).lastrowid
        except Exception:
            raise ErroUsuario("Login já existente.")
        plano = b.get("plano") if b.get("plano") in ("basico", "analista", "corporativo") else "basico"
        dias = int(b.get("dias") or 365)
        c.execute("INSERT INTO assinaturas(usuario_id,plano,inicio,fim) VALUES(?,?,?,?)", (uid, plano, time.time(), time.time() + dias * 86400))
    db.auditar("usuario_criado", ctx.usuario, ctx.ip, {"login": login, "plano": plano})
    return ctx.h.json({"ok": True, "senha_temporaria": temp, "aviso": "Entregue a senha temporária por canal seguro; o usuário deverá trocá-la no 1º acesso."})


@rota("POST", r"/api/mnt/usuarios/(\d+)/redefinir", "mantenedor")
def usuario_redefinir(ctx, uid):
    temp = secrets.token_urlsafe(9) + "!a1"
    with db.sis() as c:
        alvo = c.execute("SELECT papel FROM usuarios WHERE id=?", (int(uid),)).fetchone()
        if not alvo or alvo["papel"] == "mantenedor":
            raise ErroUsuario("Operação não permitida para esta conta.")
        c.execute("UPDATE usuarios SET senha=?, trocar_senha=1, falhas=0, bloqueado_ate=0, totp=NULL WHERE id=?", (S.hash_senha(temp), int(uid)))
        c.execute("DELETE FROM sessoes WHERE usuario_id=?", (int(uid),))
    db.auditar("usuario_redefinido", ctx.usuario, ctx.ip, {"id": uid})
    return ctx.h.json({"ok": True, "senha_temporaria": temp})


# ---------- assinaturas ----------
@rota("GET", "/api/mnt/assinaturas", "mantenedor")
def assinaturas(ctx):
    with db.sis() as c:
        rs = c.execute("""SELECT a.id, u.login, u.nome, a.plano, a.inicio, a.fim, a.situacao, a.obs FROM assinaturas a JOIN usuarios u ON u.id=a.usuario_id
                          ORDER BY a.id DESC""").fetchall()
        planos = [dict(r) for r in c.execute("SELECT * FROM planos")]
    return ctx.h.json({"assinaturas": [dict(r) for r in rs], "planos": planos})


@rota("POST", "/api/mnt/assinaturas", "mantenedor")
def assinatura_salvar(ctx):
    b = ctx.corpo
    if b.get("plano") not in ("basico", "analista", "corporativo") or b.get("situacao", "ativa") not in ("ativa", "suspensa", "cancelada"):
        raise ErroUsuario("Plano ou situação inválidos.")
    fim = time.time() + int(b.get("dias") or 365) * 86400
    with db.sis() as c:
        if b.get("id"):
            c.execute("UPDATE assinaturas SET plano=?, fim=?, situacao=?, obs=? WHERE id=?", (b["plano"], fim, b.get("situacao", "ativa"), texto(b.get("obs"), 300, False), int(b["id"])))
        else:
            u = c.execute("SELECT id FROM usuarios WHERE login=?", ((b.get("login") or "").lower(),)).fetchone()
            if not u:
                raise ErroUsuario("Usuário não encontrado.")
            c.execute("INSERT INTO assinaturas(usuario_id,plano,inicio,fim,obs) VALUES(?,?,?,?,?)", (u["id"], b["plano"], time.time(), fim, texto(b.get("obs"), 300, False)))
    db.auditar("assinatura_salva", ctx.usuario, ctx.ip, {k: b.get(k) for k in ("id", "login", "plano", "situacao", "dias")})
    return ctx.h.json({"ok": True})


# ---------- auditoria ----------
@rota("GET", "/api/mnt/auditoria", "mantenedor")
def auditoria(ctx):
    filtro = (ctx.params.get("acao") or "")[:40]
    with db.sis() as c:
        rs = c.execute("SELECT id, quando, login, ip, acao, detalhe FROM auditoria WHERE acao LIKE ? ORDER BY id DESC LIMIT 500", (f"%{filtro}%",)).fetchall()
    return ctx.h.json({"registros": [dict(r) for r in rs], "cadeia": db.verificar_cadeia()})


# ---------- SAC (atendimento) ----------
@rota("GET", "/api/mnt/sac", "mantenedor")
def sac_todos(ctx):
    with db.sis() as c:
        rs = c.execute("SELECT id, protocolo, nome, email, assunto, categoria, situacao, criado, atualizado FROM sac_chamados ORDER BY situacao='encerrado', atualizado DESC LIMIT 300").fetchall()
    return ctx.h.json([dict(r) for r in rs])


@rota("GET", r"/api/mnt/sac/(\d+)", "mantenedor")
def sac_detalhe(ctx, cid):
    with db.sis() as c:
        ch = c.execute("SELECT * FROM sac_chamados WHERE id=?", (int(cid),)).fetchone()
        ms = c.execute("SELECT autor, interno, texto, quando FROM sac_mensagens WHERE chamado_id=? ORDER BY id", (int(cid),)).fetchall()
    if not ch:
        return ctx.h.nao_encontrado()
    return ctx.h.json({"chamado": dict(ch), "mensagens": [dict(m) for m in ms]})


@rota("POST", r"/api/mnt/sac/(\d+)", "mantenedor")
def sac_atender(ctx, cid):
    sit = ctx.corpo.get("situacao") if ctx.corpo.get("situacao") in ("aberto", "em atendimento", "respondido", "encerrado") else "respondido"
    with db.sis() as c:
        if ctx.corpo.get("texto"):
            c.execute("INSERT INTO sac_mensagens(chamado_id,autor,interno,texto,quando) VALUES(?,?,?,?,?)",
                      (int(cid), "suporte", 1 if ctx.corpo.get("interno") else 0, texto(ctx.corpo.get("texto"), 4000), time.time()))
        c.execute("UPDATE sac_chamados SET situacao=?, atualizado=? WHERE id=?", (sit, time.time(), int(cid)))
    db.auditar("sac_atendido", ctx.usuario, ctx.ip, {"chamado": cid, "situacao": sit})
    return ctx.h.json({"ok": True})


# ---------- rede, coleta e processamento ----------
@rota("GET", "/api/mnt/rede", "mantenedor")
def diag_rede(ctx):
    db.auditar("diagnostico_rede", ctx.usuario, ctx.ip)
    return ctx.h.json(rede.diagnostico())


@rota("POST", "/api/mnt/rede", "mantenedor")
def cfg_rede(ctx):
    """Grava endereço do proxy SEM credenciais (credenciais só por variável de ambiente)."""
    px = (ctx.corpo.get("proxy") or "").strip()
    if px and not re.fullmatch(r"https?://[A-Za-z0-9\.\-]+:\d{2,5}/?", px):
        raise ErroUsuario("Informe no formato http://servidor:porta (sem usuário/senha).")
    ca = (ctx.corpo.get("ca_bundle") or "").strip()
    if ca and not os.path.isfile(ca):
        raise ErroUsuario("Arquivo de certificado não encontrado no servidor.")
    CFG["rede"]["proxy"] = px; CFG["rede"]["ca_bundle"] = ca
    salvar_parcial("rede", {k: CFG["rede"][k] for k in ("proxy", "usar_proxy_do_sistema", "ca_bundle", "timeout_seg", "tentativas")})
    rede.decidir_proxy(forcar=True)
    db.auditar("rede_configurada", ctx.usuario, ctx.ip, {"proxy": px, "ca": bool(ca)})
    return ctx.h.json({"ok": True})


def _rodar(etapas):
    _JOB["ativo"] = True
    try:
        processar_tudo(etapas, lambda e: _JOB.__setitem__("etapa", e))
    finally:
        _JOB.update(ativo=False, etapa=None)


@rota("POST", "/api/mnt/coleta", "mantenedor")
def coleta(ctx):
    if _JOB["ativo"]:
        raise ErroUsuario("Já existe uma coleta em andamento.")
    etapas = [e for e in (ctx.corpo.get("etapas") or []) if e in fontes.ETAPAS] or fontes.PADRAO_COLETA
    threading.Thread(target=_rodar, args=(etapas,), daemon=True).start()
    db.auditar("coleta_iniciada", ctx.usuario, ctx.ip, {"etapas": etapas})
    return ctx.h.json({"ok": True, "etapas": etapas})


@rota("POST", "/api/mnt/estatistica", "mantenedor")
def recalcular(ctx):
    if _JOB["ativo"]:
        raise ErroUsuario("Aguarde a coleta em andamento.")
    threading.Thread(target=_rodar, args=([],), daemon=True).start()
    return ctx.h.json({"ok": True})


def _upload(fn):
    fn.upload = True
    return fn


@rota("POST", "/api/mnt/atacado", "mantenedor")
@_upload
def importar_atacado(ctx):
    if PUBLICA:
        raise ErroUsuario("Edição pública: a base de clientes não pode ser importada neste servidor.")
    b = ctx.corpo.get("_bytes") or b""
    if not b.startswith(b"PK"):
        raise ErroUsuario("Envie o arquivo .xlsx da base de clientes.")
    fd, p = tempfile.mkstemp(suffix=".xlsx", dir=DIR_DADOS)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(b)
        try:
            n = atacado.importar(p)
        except Exception:
            raise ErroUsuario("Não foi possível ler a planilha. Verifique se é a base DB5186 em .xlsx.")
    finally:
        os.remove(p)
    estatistica.carteira(); estatistica.credores()
    db.auditar("atacado_importado", ctx.usuario, ctx.ip, {"cnpjs": n})
    return ctx.h.json({"ok": True, "cnpjs": n})


@rota("POST", "/api/mnt/sessoes/encerrar-todas", "mantenedor")
def derrubar(ctx):
    with db.sis() as c:
        c.execute("DELETE FROM sessoes WHERE token_h<>?", (ctx.sessao["token_h"],))
    db.auditar("todas_sessoes_encerradas", ctx.usuario, ctx.ip)
    return ctx.h.json({"ok": True})
