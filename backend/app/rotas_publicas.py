"""Portal público.
- Conteúdo agregado de fontes públicas; nenhum dado da carteira ou do PSI passa por aqui.
- Prévia livre; conteúdo completo exige cadastro do interessado (configurável em portal.exigir_cadastro).
  A regra é aplicada NO SERVIDOR: sem cadastro, as rotas devolvem só a prévia.
- Respostas pré-serializadas, recalculadas quando a estatística é atualizada."""
import json, threading, time
from .servidor import rota, COOKIE_VIS, expurgar_interessados
from .config import CFG
from . import db, seguranca as S
from .seguranca import ErroUsuario, texto

_CACHE = {"chave": None, "completo": {}, "previa": {}}
_LOCK = threading.Lock()
PERFIS = ["Pesquisa acadêmica", "Advocacia / administração judicial", "Instituição financeira", "Empresa / consultoria", "Imprensa", "Setor público", "Outro"]
CONSENTIMENTO = ("Autorizo o tratamento dos dados informados para liberar o acesso ao conteúdo do Observatório e, se marcado, "
                 "para receber comunicações sobre atualizações. Posso pedir a exclusão a qualquer momento pelo Fale conosco.")


def _montar():
    g = db.estat_get
    nac = g("nacional", {}) or {}
    av = g("avancado") or {}
    cred = g("credores") or {}
    conc = g("concentracao") or {}
    pr = g("processos") or {}
    procs_cred = [{k: p.get(k) for k in ("processo", "tribunal", "rj_re", "devedora", "passivo", "bancos_%", "confianca", "tipo_edital")}
                  for p in (cred.get("processos") or [])[:100]]
    completo = {
        "tendencia": {k: av.get(k) for k in ("meses", "observado", "tendencia", "indices_sazonais", "previsao_meses", "previsao_ensemble",
                                             "previsao_modelos", "pesos_ensemble", "validacao", "holt_winters", "regimes")}
                     | {"uf": nac.get("uf_rj"), "varas": nac.get("varas"), "anual": nac.get("anual")},
        "macro": {"series": nac.get("macro"), "curva": nac.get("curva"), "focus": nac.get("focus"), "correlacoes": g("macro_correlacoes"),
                  "modelo": g("macro_modelo"), "projecao": g("macro_projecao"), "status": g("macro_status")},
        "credores": {"classes": cred.get("classes"), "bancos": cred.get("bancos"), "confianca": cred.get("confianca"),
                     "lista_em_anexo": cred.get("lista_em_anexo"), "processos": procs_cred, "concentracao": conc},
        "processos": pr,
    }
    previa = {
        "tendencia": {"previa": True, "indices_sazonais": av.get("indices_sazonais")},
        "macro": {"previa": True, "series": nac.get("macro")},
        "credores": {"previa": True, "classes": cred.get("classes"), "n_processos": len(cred.get("processos") or [])},
        "processos": {"previa": True, **{k: pr.get(k) for k in ("total", "com_datajud", "com_edital", "por_tipo")}} if pr else {"previa": True},
    }
    resumo = {"atualizado": g("atualizado_em"), "acumulado_12m": av.get("acumulado_12m"), "variacao_12m_%": av.get("variacao_12m_%"),
              "proximos_12m": round(sum(p["previsto"] for p in av.get("previsao_ensemble") or []), 0) if av.get("previsao_ensemble") else None,
              "passivo_listado": sum(p.get("passivo") or 0 for p in cred.get("processos") or []) or None,
              "processos_credores": len(cred.get("processos") or []), "hhi_bancos": conc.get("hhi_bancos_agregado"),
              "processos_identificados": pr.get("total"), "serie_12m": (av.get("observado") or [])[-24:],
              "grafico": {k: av.get(k) for k in ("meses", "observado", "tendencia", "previsao_meses", "previsao_ensemble", "regimes", "indices_sazonais")}}
    enc = lambda d: {k: json.dumps(v, ensure_ascii=False, default=str, separators=(",", ":")).encode() for k, v in d.items()}
    out_c, out_p = enc(completo), enc(previa)
    out_c["resumo"] = out_p["resumo"] = json.dumps(resumo, ensure_ascii=False, default=str, separators=(",", ":")).encode()
    out_c["coleta"] = out_p["coleta"] = json.dumps(g("coleta") or {}, ensure_ascii=False, default=str, separators=(",", ":")).encode()
    return out_c, out_p


def _dados(liberado):
    chave = db.estat_get("atualizado_em")
    with _LOCK:
        if chave != _CACHE["chave"] or not _CACHE["completo"]:
            _CACHE["completo"], _CACHE["previa"] = _montar()
            _CACHE["chave"] = chave
        return _CACHE["completo"] if liberado else _CACHE["previa"]


@rota("GET", "/api/publico/(resumo|coleta)", "publico")
def publico_livre(ctx, secao):
    return ctx.h.json(_dados(True)[secao], cache="publico")


@rota("GET", "/api/publico/(tendencia|macro|credores|processos)", "publico")
def publico_restrito(ctx, secao):
    return ctx.h.json(_dados(ctx.liberado)[secao], cache="privado")


@rota("GET", "/api/publico/privacidade", "publico")
def privacidade(ctx):
    p = CFG["portal"]
    return ctx.h.json({"controlador": p.get("controlador") or None, "email": p.get("email_privacidade") or None, "retencao_dias": p.get("retencao_dias"),
                       "validade_cadastro_dias": p.get("validade_cadastro_dias"), "perfis": PERFIS, "consentimento": CONSENTIMENTO}, cache="publico")


@rota("POST", "/api/publico/cadastro", "publico")
def cadastro(ctx):
    if not S.CADASTRO_IP.permitido(ctx.ip):
        raise ErroUsuario("Muitos cadastros a partir desta conexão. Tente mais tarde.")
    if ctx.corpo.get("site"):  # campo-isca anti-robô
        return ctx.h.json({"ok": True})
    nome = texto(ctx.corpo.get("nome"), 120)
    email = texto(ctx.corpo.get("email"), 200).lower()
    if not S.RX_EMAIL.match(email):
        raise ErroUsuario("Informe um e-mail válido.")
    perfil = ctx.corpo.get("perfil") if ctx.corpo.get("perfil") in PERFIS else None
    if not perfil:
        raise ErroUsuario("Selecione o perfil.")
    if ctx.corpo.get("consentimento") not in (True, "on", "true", "1"):
        raise ErroUsuario("É necessário concordar com o uso dos dados para liberar o acesso.")
    org = texto(ctx.corpo.get("organizacao"), 160, obrig=False)
    interesse = texto(ctx.corpo.get("interesse"), 500, obrig=False)
    novidades = 1 if ctx.corpo.get("novidades") in (True, "on", "true", "1") else 0
    S.CADASTRO_IP.registra(ctx.ip)
    tok = S.novo_token(); agora = time.time(); dias = CFG["portal"].get("validade_cadastro_dias", 180)
    with db.sis() as c:
        ex = c.execute("SELECT id FROM interessados WHERE email=?", (email,)).fetchone()
        if ex:
            c.execute("""UPDATE interessados SET nome=?, organizacao=?, perfil=?, interesse=?, novidades=?, consentimento=?, token_h=?, expira=?,
                         ultimo_acesso=?, acessos=acessos+1 WHERE id=?""", (nome, org, perfil, interesse, novidades, CONSENTIMENTO, S.h256(tok), agora + dias * 86400, agora, ex["id"]))
            iid = ex["id"]
        else:
            iid = c.execute("""INSERT INTO interessados(nome,email,organizacao,perfil,interesse,novidades,consentimento,criado,ultimo_acesso,acessos,token_h,expira,ip_h)
                               VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?)""", (nome, email, org, perfil, interesse, novidades, CONSENTIMENTO, agora, agora,
                                                                    S.h256(tok), agora + dias * 86400, S.h256(ctx.ip)[:16])).lastrowid
    expurgar_interessados()
    db.auditar("cadastro_portal", None, ctx.ip, {"interessado": iid, "perfil": perfil})
    seguro = "; Secure" if CFG["servidor"]["https_atras_de_proxy_reverso"] else ""
    return ctx.h.json({"ok": True, "nome": nome.split(" ")[0]}, extra={"Set-Cookie": f"{COOKIE_VIS}={tok}; HttpOnly; SameSite=Lax; Path=/{seguro}; Max-Age={dias * 86400}"})


@rota("POST", "/api/publico/cadastro/sair", "publico")
def cadastro_sair(ctx):
    return ctx.h.json({"ok": True}, extra={"Set-Cookie": f"{COOKIE_VIS}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"})
