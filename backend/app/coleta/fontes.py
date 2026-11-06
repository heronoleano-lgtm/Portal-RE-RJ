"""Coletores das APIs públicas – somente biblioteca padrão.
Etapas: datajud (contagens) · djen (publicações) · credores (editais) · cvm · macro (SGS, Focus, Tesouro)
        · enriquecer (consulta no DataJud, processo a processo, dos números encontrados no DJEN) · observatorio (referência)"""
import csv, datetime as dt, io, json, logging, os, re, time, zipfile
from ..config import CFG, DIR_DADOS
from ..db import ana, estat_set
from ..rede import requisitar, requisitar_json

log = logging.getLogger("motor.coleta")
dig = lambda x: re.sub(r"\D", "", str(x or ""))


def _exec(etapa, fn):
    t0 = time.time()
    with ana() as c:
        rid = c.execute("INSERT INTO coleta_execucoes(etapa,inicio,situacao) VALUES(?,?,'em andamento')", (etapa, t0)).lastrowid
    try:
        n, nota = fn()
        sit = "concluída" if n else "sem dados"
    except Exception:
        log.exception("Etapa %s falhou", etapa)
        n, nota, sit = 0, "falha – ver log do servidor", "falha"
    with ana() as c:
        c.execute("UPDATE coleta_execucoes SET fim=?,situacao=?,linhas=?,nota=? WHERE id=?", (time.time(), sit, n, nota, rid))
    return sit, n


# ---------------- DataJud ----------------
def _chave_datajud(renovar=False):
    if renovar:
        st, b = requisitar(CFG["datajud"]["wiki_chave"], tentativas=1)
        m = re.search(rb"APIKey\s+([A-Za-z0-9+/=_\-]{40,})", b or b"")
        if m:
            CFG["datajud"]["chave_publica"] = m.group(1).decode()
    return CFG["datajud"]["chave_publica"]


def _dj_post(trib, corpo):
    url = f"https://api-publica.datajud.cnj.jus.br/api_publica_{trib}/_search"
    for renovar in (False, True):
        st, b = requisitar(url, "POST", corpo, {"Authorization": "APIKey " + _chave_datajud(renovar)}, timeout=75)
        if st in (401, 403) and not renovar:
            continue
        if st == 200 and b:
            return json.loads(b)
        return None


def datajud():
    d = CFG["datajud"]
    def run():
        n = 0
        with ana() as c:
            for tipo, cod in d["classes"].items():
                for t in d["tribunais"]:
                    j = _dj_post(t, {"size": 0, "query": {"bool": {"filter": [{"term": {"classe.codigo": cod}},
                                     {"range": {"dataAjuizamento": {"gte": f"{d['ano_inicial']}-01-01"}}}]}},
                                     "aggs": {"mes": {"date_histogram": {"field": "dataAjuizamento", "calendar_interval": "month", "format": "yyyy-MM"}},
                                              "org": {"terms": {"field": "orgaoJulgador.nome.keyword", "size": 20}}}})
                    if not j:
                        continue
                    a = j.get("aggregations", {})
                    for b in a.get("mes", {}).get("buckets", []):
                        c.execute("INSERT OR REPLACE INTO datajud_mensal VALUES(?,?,?,?,?)", (t.upper(), t[2:].upper(), tipo, b["key_as_string"], b["doc_count"])); n += 1
                    for b in a.get("org", {}).get("buckets", []):
                        c.execute("INSERT OR REPLACE INTO datajud_varas VALUES(?,?,?,?)", (t.upper(), tipo, b["key"], b["doc_count"]))
        return n, f"{n} linhas mês×tribunal"
    return _exec("datajud", run)


def _data(v):
    """Normaliza datas do DataJud (ISO 'AAAA-MM-DD...' ou compacta 'AAAAMMDDhhmmss') para 'AAAA-MM-DD'."""
    v = str(v or "")
    if re.match(r"^\d{8}", v):
        return f"{v[:4]}-{v[4:6]}-{v[6:8]}"
    return v[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", v) else None


def _marco(movs, *chaves):
    """Primeira data de movimento cujo nome contém todas as palavras-chave (identificação por texto do movimento)."""
    ds = [_data(m.get("dataHora")) for m in movs if m.get("dataHora") and all(k in (m.get("nome") or "").lower() for k in chaves)]
    ds = [d for d in ds if d]
    return min(ds) if ds else None


def parse_processo(src):
    """Converte um documento (_source) da API Pública do DataJud nos campos usados no cruzamento."""
    mv = src.get("movimentos") or []
    org = src.get("orgaoJulgador") or {}
    classe = src.get("classe") or {}
    datas = [d for d in (_data(m.get("dataHora")) for m in mv) if d]
    aj = _data(src.get("dataAjuizamento"))
    return {"classe_codigo": classe.get("codigo"), "classe_nome": classe.get("nome"), "ajuizamento": aj,
            "orgao": org.get("nome"), "mun_ibge": str(org.get("codigoMunicipioIBGE") or "") or None,
            "assuntos": ";".join(a.get("nome", "") for a in (src.get("assuntos") or []) if isinstance(a, dict))[:500],
            "n_movs": len(mv), "dt_deferimento": _marco(mv, "defer"), "dt_concessao": _marco(mv, "concess"),
            "dt_convolacao": _marco(mv, "decreta", "fal") or _marco(mv, "convola"), "dt_encerramento": _marco(mv, "encerr") or _marco(mv, "arquiv"),
            "dt_ultima_mov": max(datas) if datas else None}


def enriquecer():
    """Para cada processo encontrado no DJEN/editais, busca no DataJud a ficha e os movimentos (consulta por numeroProcesso)."""
    d = CFG["datajud"]
    def run():
        limite = time.time() - d.get("reconsultar_dias", 30) * 86400
        with ana() as c:
            alvos = c.execute("""SELECT p.processo, MAX(lower(p.tribunal)) trib FROM (
                                   SELECT processo, tribunal FROM djen_publicacoes UNION SELECT processo, tribunal FROM djen_editais) p
                                 LEFT JOIN datajud_processos dp ON dp.processo = p.processo
                                 WHERE length(p.processo)=20 AND (dp.processo IS NULL OR dp.consultado < ?)
                                 GROUP BY p.processo LIMIT ?""", (limite, d.get("enriquecer_max", 400))).fetchall()
        n = 0
        for proc, trib in alvos:
            if (trib or "") not in d["tribunais"]:
                continue
            j = _dj_post(trib, {"size": 1, "query": {"match": {"numeroProcesso": proc}}})
            hits = (j or {}).get("hits", {}).get("hits", [])
            with ana() as c:
                if hits:
                    r = parse_processo(hits[0].get("_source", {}))
                    c.execute("""INSERT OR REPLACE INTO datajud_processos VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                              (proc, trib.upper(), r["classe_codigo"], r["classe_nome"], r["ajuizamento"], r["orgao"], r["mun_ibge"], r["assuntos"],
                               r["n_movs"], r["dt_deferimento"], r["dt_concessao"], r["dt_convolacao"], r["dt_encerramento"], r["dt_ultima_mov"], time.time()))
                    n += 1
                elif j is not None:
                    c.execute("INSERT OR REPLACE INTO datajud_processos(processo, tribunal, encontrado, consultado) VALUES(?,?,0,?)", (proc, trib.upper(), time.time()))
        return n, f"{n} de {len(alvos)} processos localizados no DataJud"
    return _exec("enriquecer", run)


# ---------------- DJEN ----------------
RX_DOC = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")


def _djen_pagina(termo, ini, fim, pag):
    j = requisitar_json("https://comunicaapi.pje.jus.br/api/v1/comunicacao",
                        params={"texto": termo, "dataDisponibilizacaoInicio": ini, "dataDisponibilizacaoFim": fim, "pagina": pag, "itensPorPagina": 100})
    return (j or {}).get("items", [])


def djen():
    def run():
        fim = dt.date.today(); ini = fim - dt.timedelta(days=CFG["djen"]["dias"]); n = 0
        with ana() as c:
            for termo in ["recuperação judicial", "recuperação extrajudicial", "convolação em falência"]:
                for pag in range(1, 51):
                    it = _djen_pagina(termo, ini.isoformat(), fim.isoformat(), pag)
                    if not it:
                        break
                    for x in it:
                        txt = x.get("texto") or ""
                        c.execute("INSERT OR IGNORE INTO djen_publicacoes VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                  (str(x.get("id") or (x.get("numero_processo"), x.get("data_disponibilizacao"))), termo, x.get("data_disponibilizacao"),
                                   x.get("siglaTribunal"), dig(x.get("numero_processo")), x.get("nomeOrgao"), x.get("tipoComunicacao"), x.get("nomeClasse"),
                                   ";".join(d.get("nome", "") for d in (x.get("destinatarios") or []) if isinstance(d, dict))[:500],
                                   ";".join(sorted({dig(m) for m in RX_DOC.findall(txt)}))[:2000], txt[:500]))
                        n += 1
        return n, f"{n} publicações"
    return _exec("djen", run)


def djen_credores():
    from .credores import processar
    def run():
        fim = dt.date.today(); ini = fim - dt.timedelta(days=CFG["djen"]["dias_credores"]); bruto = []
        for termo in ["relação de credores", "relação nominal de credores", "quadro geral de credores", "art. 7º, § 2º", "art. 52, § 1º"]:
            for pag in range(1, 101):
                it = _djen_pagina(termo, ini.isoformat(), fim.isoformat(), pag)
                if not it:
                    break
                bruto += it
        return processar(bruto)
    return _exec("credores", run)


# ---------------- CVM ----------------
def cvm():
    def run():
        st, b = requisitar("https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv")
        if st != 200 or not b:
            return 0, "sem retorno"
        n = 0
        with ana() as c:
            c.execute("DELETE FROM cvm_insolvencia")
            for r in csv.DictReader(io.StringIO(b.decode("latin1")), delimiter=";"):
                s = (r.get("SIT_EMISSOR") or "").upper()
                if re.search("RECUPERA|FAL|LIQUIDA", s):
                    c.execute("INSERT OR REPLACE INTO cvm_insolvencia VALUES(?,?,?,?,?,?)",
                              (dig(r.get("CNPJ_CIA")).zfill(14), r.get("DENOM_SOCIAL"), r.get("SETOR_ATIV"), r.get("SIT_EMISSOR"), r.get("DT_INI_SIT_EMISSOR"), r.get("UF"))); n += 1
        return n, f"{n} companhias"
    return _exec("cvm", run)


# ---------------- Macro: BCB SGS, Focus, Tesouro ----------------
def macro():
    def run():
        n = 0
        with ana() as c:
            for nome, cod in CFG["bcb_series"].items():
                j = requisitar_json(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados", params={"formato": "json", "dataInicial": f"01/01/{CFG['datajud']['ano_inicial'] - 2}"})
                if not j:
                    log.warning("Série SGS %s (%s) sem retorno – conferir código", nome, cod); continue
                acc = {}
                for p in j:
                    try:
                        d = dt.datetime.strptime(p["data"], "%d/%m/%Y"); v = float(p["valor"])
                    except (KeyError, ValueError):
                        continue
                    acc.setdefault(d.strftime("%Y-%m"), []).append(v)
                for m, vs in acc.items():
                    c.execute("INSERT OR REPLACE INTO macro_mensal VALUES(?,?,?)", (nome, m, sum(vs) / len(vs))); n += 1
            ini = (dt.date.today() - dt.timedelta(days=45)).isoformat()
            j = requisitar_json("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais",
                                params={"$format": "json", "$top": 5000, "$filter": f"Data ge '{ini}' and baseCalculo eq 0"})
            vals = [v for v in (j or {}).get("value", []) if v.get("Indicador") in ("Selic", "IPCA", "PIB Total", "Câmbio")]
            if vals:
                ult = max(v["Data"] for v in vals)
                c.execute("DELETE FROM focus")
                for v in vals:
                    if v["Data"] == ult:
                        c.execute("INSERT OR REPLACE INTO focus VALUES(?,?,?,?)", (v["Indicador"], str(v["DataReferencia"]), v["Mediana"], v["Data"]))
        n += _curva()
        return n, f"{n} pontos macro/curva"
    return _exec("macro", run)


def _curva():
    st, b = requisitar(CFG["tesouro_csv"], timeout=120)
    if st != 200 or not b:
        return 0
    linhas = []
    for r in csv.DictReader(io.StringIO(b.decode("latin1")), delimiter=";"):
        tt = r.get("Tipo Titulo", "")
        curva = "Prefixada" if "Prefixado" in tt else ("Real (IPCA+)" if "IPCA+" in tt and not re.search("Renda|Educa", tt) else None)
        if not curva:
            continue
        try:
            db_ = dt.datetime.strptime(r["Data Base"], "%d/%m/%Y"); dv = dt.datetime.strptime(r["Data Vencimento"], "%d/%m/%Y")
            tx = float(r["Taxa Compra Manha"].replace(",", "."))
        except (KeyError, ValueError):
            continue
        linhas.append((db_, curva, tt, dv, (dv - db_).days / 365.25, tx))
    if not linhas:
        return 0
    datas = sorted({l[0] for l in linhas}); hoje = datas[-1]
    def ate(dias):
        alvo = hoje - dt.timedelta(days=dias)
        return max([d for d in datas if d <= alvo] or [datas[0]])
    momentos = {"hoje": hoje, "-6m": ate(182), "-12m": ate(365), "-24m": ate(730)}
    with ana() as c:
        c.execute("DELETE FROM curva"); c.execute("DELETE FROM curva_mensal")
        for k, d in momentos.items():
            for l in linhas:
                if l[0] == d:
                    c.execute("INSERT INTO curva VALUES(?,?,?,?,?,?,?)", (k, d.date().isoformat(), l[1], l[2], l[3].date().isoformat(), round(l[4], 3), l[5]))
        por_mes = {}
        for l in linhas:
            por_mes.setdefault(l[0].strftime("%Y-%m"), []).append(l)
        for m, ls in por_mes.items():
            def pto(curva, alvo):
                cs = [x for x in ls if x[1] == curva]
                return min(cs, key=lambda x: abs(x[4] - alvo))[5] if cs else None
            pc, pl, jr = pto("Prefixada", 1.5), pto("Prefixada", 6), pto("Real (IPCA+)", 5)
            c.execute("INSERT OR REPLACE INTO curva_mensal VALUES(?,?,?,?,?)", (m, pc, pl, jr, (pl - pc) if pc is not None and pl is not None else None))
    return len(por_mes)


# ---------------- Observatório da Insolvência (referência metodológica, GitHub) ----------------
def observatorio():
    """Baixa os arquivos do relatório público do Observatório da Insolvência (RJ em SP). Não entra nos cálculos do portal."""
    def run():
        dst = os.path.join(DIR_DADOS, "observatorio"); os.makedirs(dst, exist_ok=True); inv = []
        for repo in CFG.get("observatorio_repos", []):
            b = None
            for br in ("master", "main"):
                st, b = requisitar(f"https://codeload.github.com/{repo}/zip/refs/heads/{br}", tentativas=1, timeout=120)
                if st == 200:
                    break
                b = None
            if not b:
                continue
            z = zipfile.ZipFile(io.BytesIO(b))
            for nm in z.namelist():
                if nm.lower().endswith((".csv", ".rds", ".rda", ".xlsx")):
                    with open(os.path.join(dst, repo.replace("/", "_") + "__" + os.path.basename(nm)), "wb") as f:
                        f.write(z.read(nm))
                    inv.append({"repositorio": repo, "arquivo": os.path.basename(nm)})
        estat_set("observatorio_inventario", inv)
        return len(inv), f"{len(inv)} arquivos"
    return _exec("observatorio", run)


ETAPAS = {"datajud": datajud, "djen": djen, "credores": djen_credores, "cvm": cvm, "macro": macro, "enriquecer": enriquecer, "observatorio": observatorio}
PADRAO_COLETA = ["datajud", "djen", "credores", "cvm", "macro", "enriquecer"]
DESCRICAO = {
    "datajud": ("CNJ – API Pública do DataJud", "Contagem mensal de processos novos por classe (RJ 129, RE 128, falência 108) nos 27 tribunais de justiça estaduais e varas com mais processos."),
    "djen": ("CNJ – Diário de Justiça Eletrônico Nacional", "Publicações com os termos recuperação judicial, recuperação extrajudicial e convolação em falência: número do processo, tribunal, órgão, partes destinatárias e CNPJs citados."),
    "credores": ("CNJ – DJEN, editais de credores", "Editais de relação de credores (art. 52 §1º, art. 7º §2º e quadro geral): credor, classe, valor e banco identificado."),
    "enriquecer": ("CNJ – DataJud, consulta por processo", "Para cada número de processo achado no DJEN: classe, data de ajuizamento, órgão julgador e movimentos (deferimento, concessão, convolação, encerramento)."),
    "cvm": ("CVM – Dados Abertos", "Cadastro de companhias abertas em recuperação judicial, extrajudicial, falência ou liquidação."),
    "macro": ("Banco Central e Tesouro", "Séries SGS (Selic, juros e spread PJ, inadimplência, crédito, câmbio, atividade), expectativas Focus e taxas dos títulos públicos."),
    "observatorio": ("Observatório da Insolvência (ABJ/NEPI PUC-SP)", "Arquivos do relatório público sobre RJ em São Paulo, usados como referência metodológica (não entram nos cálculos)."),
}
