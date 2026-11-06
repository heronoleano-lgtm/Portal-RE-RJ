"""Cruzamento das bases coletadas (camada de aplicação).

Entradas: djen_publicacoes · djen_editais · credores · datajud_processos (consulta por número) · cvm_insolvencia
Saídas  : partes    – uma linha por (processo, parte, papel), com fonte e evidência
          processos – uma linha por processo, unindo DJEN + edital + DataJud + CVM
          grupos    – empresas ligadas por aparecerem como devedoras no mesmo processo (litisconsórcio) ou em vários processos

Regras de prudência (nada é inferido além do que está nos dados):
- "devedora" só quando o CNPJ aparece no CABEÇALHO do edital de credores (antes da 1ª classe);
- CNPJs encontrados no texto de outras publicações ficam como "citada" (não se presume o polo);
- destinatários do DJEN sem característica de pessoa jurídica não têm o nome gravado (proteção de pessoas físicas);
- tipo do processo: classe do DataJud > classe informada no DJEN > tipo do edital; senão "Não identificado".
"""
import datetime as dt, logging, re, unicodedata
from .db import ana

log = logging.getLogger("motor.integracao")
RX_PJ = re.compile(r"\b(LTDA|S\.?\s?A\.?|S/A|EIRELI|\bME\b|\bEPP\b|CIA\.?|COMPANHIA|COOPERATIVA|ASSOCIA[CÇ][AÃ]O|BANCO|FUNDO|"
                   r"CONS[OÓ]RCIO|\bSPE\b|HOLDING|EMPREENDIMENTOS|IND[UÚ]STRIA|COM[EÉ]RCIO|PARTICIPA[CÇ][OÕ]ES|AGRO|TRANSPORTES|"
                   r"CONSTRU|SERVI[CÇ]OS|MASSA FALIDA|EM RECUPERA[CÇ][AÃ]O|FAZENDA NACIONAL|UNI[AÃ]O|MUNIC[IÍ]PIO|ESTADO D)", re.I)


def _sa(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").upper()


def eh_pj(nome):
    return bool(nome and RX_PJ.search(_sa(nome)))


def uf_de(trib):
    t = (trib or "").upper()
    if t == "TJDFT":
        return "DF"
    return t[2:4] if t.startswith("TJ") and len(t) >= 4 else None


def tipo_por_texto(t):
    s = _sa(t)
    if "EXTRAJUDICIAL" in s:
        return "RE"
    if "RECUPERACAO JUDICIAL" in s:
        return "RJ"
    if "FALENCIA" in s:
        return "FAL"
    return None


def _dias(a, b):
    try:
        d = (dt.date.fromisoformat(b[:10]) - dt.date.fromisoformat(a[:10])).days
        return d if d >= 0 else None
    except (TypeError, ValueError):
        return None


class _UF:
    def __init__(self):
        self.p = {}

    def acha(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x

    def une(self, a, b):
        ra, rb = self.acha(a), self.acha(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def integrar():
    with ana() as c:
        pubs = [dict(r) for r in c.execute("SELECT * FROM djen_publicacoes WHERE length(processo)=20")]
        eds = [dict(r) for r in c.execute("SELECT * FROM djen_editais WHERE length(processo)=20")]
        cred = [dict(r) for r in c.execute("SELECT k.* FROM credores k JOIN djen_editais e ON e.id=k.edital_id WHERE e.vigente=1")]
        dj = {r["processo"]: dict(r) for r in c.execute("SELECT * FROM datajud_processos WHERE encontrado=1")}
        cvm = {r["cnpj"][:8]: (r["nome"], r["situacao"]) for r in c.execute("SELECT cnpj, nome, situacao FROM cvm_insolvencia")}

    partes, chaves = [], set()
    nomes_cnpj = {}  # cnpj -> nome conhecido (credores PJ, CVM)

    def add(proc, cnpj, nome, papel, fonte, tipo="PJ", banco=None, valor=None, classe=None):
        k = (proc, cnpj or _sa(nome), papel)
        if k in chaves:
            return
        chaves.add(k)
        raiz = cnpj[:8] if cnpj and len(cnpj) == 14 else None
        partes.append({"processo": proc, "cnpj": cnpj or None, "raiz": raiz, "nome": nome, "tipo_pessoa": tipo, "papel": papel, "fonte": fonte,
                       "banco": banco, "valor": valor, "classe_credito": classe, "cvm_situacao": cvm.get(raiz, (None, None))[1] if raiz else None})

    for k in cred:  # credores (edital vigente)
        doc = k["doc"] if k["doc"] and len(k["doc"]) == 14 else None
        if doc and k["credor"] and k["tipo_pessoa"] == "PJ":
            nomes_cnpj.setdefault(doc, k["credor"])
        pf = k["tipo_pessoa"] == "PF"
        add(k["processo"], doc, None if pf else k["credor"], "credora", "Edital (DJEN)", "PF" if pf else ("PJ" if doc else "ND"),
            k["banco"], k["valor"] if k["moeda"] == "BRL" else None, k["classe"])
    pj_destinatarios = {}
    pf_omitidos = 0
    for p in pubs:
        nomes = [n.strip() for n in (p["partes"] or "").split(";") if n.strip()]
        for n in nomes:
            if eh_pj(n):
                pj_destinatarios.setdefault(p["processo"], [])
                if n.upper() not in pj_destinatarios[p["processo"]]:
                    pj_destinatarios[p["processo"]].append(n.upper())
                add(p["processo"], None, n.upper()[:150], "destinatária", "DJEN")
            else:
                pf_omitidos += 1
        for cn in [x for x in (p["cnpjs"] or "").split(";") if len(x) == 14]:
            add(p["processo"], cn, None, "citada", "DJEN")

    for e in eds:  # devedora = CNPJ no cabeçalho do edital
        for cn in [x for x in (e["cnpjs_devedora"] or "").split(";") if len(x) == 14]:
            add(e["processo"], cn, None, "devedora", "Edital (DJEN)")

    # nomes para CNPJs sem nome: CVM > credor conhecido > destinatário PJ único do mesmo processo
    for pt in partes:
        if pt["cnpj"] and not pt["nome"]:
            raiz = pt["raiz"]
            pt["nome"] = (cvm.get(raiz, (None,))[0] or nomes_cnpj.get(pt["cnpj"]) or
                          (pj_destinatarios[pt["processo"]][0] if pt["papel"] == "devedora" and len(pj_destinatarios.get(pt["processo"], [])) == 1 else None))

    # ---------------- processos ----------------
    proc_ids = sorted({p["processo"] for p in pubs} | {e["processo"] for e in eds})
    por_proc_pub = {}
    for p in pubs:
        por_proc_pub.setdefault(p["processo"], []).append(p)
    ed_vig = {e["processo"]: e for e in eds if e["vigente"]}
    ed_qq = {}
    for e in eds:
        ed_qq.setdefault(e["processo"], e)
    cred_proc = {}
    for k in cred:
        d = cred_proc.setdefault(k["processo"], {"passivo": 0.0, "bancos": 0.0, "n": 0})
        d["n"] += 1
        if k["moeda"] == "BRL":
            d["passivo"] += k["valor"] or 0
            if k["banco"]:
                d["bancos"] += k["valor"] or 0
    partes_proc = {}
    for pt in partes:
        partes_proc.setdefault(pt["processo"], []).append(pt)

    uf_ = _UF()
    for pid in proc_ids:
        devs = sorted({pt["raiz"] for pt in partes_proc.get(pid, []) if pt["papel"] == "devedora" and pt["raiz"]})
        for r in devs:
            uf_.acha(r)
        for a, b in zip(devs, devs[1:]):
            uf_.une(a, b)

    linhas = []
    for pid in proc_ids:
        ps = por_proc_pub.get(pid, [])
        d = dj.get(pid, {})
        e = ed_vig.get(pid) or ed_qq.get(pid)
        trib = (d.get("tribunal") or (ps[0]["tribunal"] if ps else None) or (e["tribunal"] if e else None) or "").upper() or None
        tipo = {129: "RJ", 128: "RE", 108: "FAL"}.get(d.get("classe_codigo"))
        if not tipo:
            for p in ps:
                tipo = tipo_por_texto(p["classe"])
                if tipo:
                    break
        if not tipo and e:
            tipo = e["rj_re"] if e["precedencia"] else None
        classe_nome = d.get("classe_nome") or next((p["classe"] for p in ps if p["classe"]), None)
        orgao = d.get("orgao") or next((p["orgao"] for p in ps if p["orgao"]), None)
        datas = sorted(p["data"] for p in ps if p["data"]) + ([e["data"]] if e and e["data"] else [])
        devp = [pt for pt in partes_proc.get(pid, []) if pt["papel"] == "devedora"]
        raizes = sorted({pt["raiz"] for pt in devp if pt["raiz"]})
        cp = cred_proc.get(pid)
        cits = [pt for pt in partes_proc.get(pid, []) if pt["papel"] in ("devedora", "citada") and pt["raiz"]]
        fontes = (["DJEN"] if ps else []) + (["Edital"] if e else []) + (["DataJud"] if d else [])
        linhas.append({
            "processo": pid, "tribunal": trib, "uf": uf_de(trib), "tipo": tipo or "Não identificado", "classe_nome": classe_nome,
            "ajuizamento": d.get("ajuizamento"), "orgao": orgao,
            "vara_especializada": int(any(x in _sa(orgao) for x in ("FALEN", "EMPRESAR", "RECUPERA"))) if orgao else None,
            "dt_deferimento": d.get("dt_deferimento"), "dt_concessao": d.get("dt_concessao"), "dt_convolacao": d.get("dt_convolacao"),
            "dt_encerramento": d.get("dt_encerramento"), "dt_ultima_mov": d.get("dt_ultima_mov"),
            "dias_deferimento": _dias(d.get("ajuizamento"), d.get("dt_deferimento")), "dias_concessao": _dias(d.get("ajuizamento"), d.get("dt_concessao")),
            "convolada": int(bool(d.get("dt_convolacao"))) if d else None,
            "primeira_pub": datas[0] if datas else None, "ultima_pub": datas[-1] if datas else None, "n_publicacoes": len(ps),
            "devedora": "; ".join(sorted({pt["nome"] for pt in devp if pt["nome"]}))[:300] or None,
            "partes_citadas": "; ".join(pj_destinatarios.get(pid, [])[:3])[:300] or None,
            "cnpj_principal": devp[0]["cnpj"] if devp else None, "n_devedoras": len(devp), "n_raizes": len(raizes),
            "grupo": int(uf_.acha(raizes[0])) if raizes else None,
            "passivo": round(cp["passivo"], 2) if cp else None, "n_credores": cp["n"] if cp else None,
            "bancos_pct": round(cp["bancos"] / cp["passivo"] * 100, 2) if cp and cp["passivo"] else None,
            "cvm": int(any(cvm.get(pt["raiz"]) for pt in cits)), "fontes": ";".join(fontes)})

    # ---------------- grupos ----------------
    comp = {}
    for l in linhas:
        for pt in partes_proc.get(l["processo"], []):
            if pt["papel"] == "devedora" and pt["raiz"]:
                g = comp.setdefault(uf_.acha(pt["raiz"]), {"raizes": set(), "procs": set(), "nomes": [], "ufs": set(), "tribs": set()})
                g["raizes"].add(pt["raiz"]); g["procs"].add(l["processo"])
                if pt["nome"] and pt["nome"] not in g["nomes"]:
                    g["nomes"].append(pt["nome"])
                if l["uf"]:
                    g["ufs"].add(l["uf"])
                if l["tribunal"]:
                    g["tribs"].add(l["tribunal"])
    grupos = [{"grupo": int(k), "n_empresas": len(g["raizes"]), "n_processos": len(g["procs"]), "nomes": "; ".join(g["nomes"][:3])[:300],
               "raizes": ";".join(sorted(g["raizes"])), "ufs": ";".join(sorted(g["ufs"])), "tribunais": ";".join(sorted(g["tribs"]))} for k, g in comp.items()]

    with ana() as c:
        c.execute("DELETE FROM partes"); c.execute("DELETE FROM processos"); c.execute("DELETE FROM grupos")
        c.executemany("INSERT INTO partes(processo,cnpj,raiz,nome,tipo_pessoa,papel,fonte,banco,valor,classe_credito,cvm_situacao) "
                      "VALUES(:processo,:cnpj,:raiz,:nome,:tipo_pessoa,:papel,:fonte,:banco,:valor,:classe_credito,:cvm_situacao)", partes)
        cols = list(linhas[0].keys()) if linhas else []
        if linhas:
            c.executemany(f"INSERT INTO processos({','.join(cols)}) VALUES({','.join(':' + k for k in cols)})", linhas)
        c.executemany("INSERT INTO grupos VALUES(:grupo,:n_empresas,:n_processos,:nomes,:raizes,:ufs,:tribunais)", grupos)
    res = {"processos": len(linhas), "partes": len(partes), "grupos": len(grupos), "pf_nao_identificadas": pf_omitidos,
           "com_datajud": sum(1 for l in linhas if "DataJud" in l["fontes"]), "com_edital": sum(1 for l in linhas if "Edital" in l["fontes"])}
    log.info("Integração: %s", res)
    return res
