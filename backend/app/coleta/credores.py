"""Extração de credores, classes e valores dos editais do DJEN.
PF é anonimizada ("PESSOA FÍSICA"); só a versão vigente de cada processo entra nas agregações."""
import html, re, unicodedata
from ..db import ana

RX_CLASSE = re.compile(r"CLASSE\s+(IV|III|II|I|4|3|2|1)\b[\s\-–—:]*(TRABALHIST\w*|GARANTIA\s+REAL|QUIROGRAF\w*|(?:MICRO|ME\s*/?\s*EPP)\w*)?|"
                       r"(CREDITOS?\s+TRABALHISTAS|CREDITOS?\s+COM\s+GARANTIA\s+REAL|CREDITOS?\s+QUIROGRAFARIOS|CREDITOS?\s+(?:DE\s+)?(?:ME|MICROEMPRESAS)[\w\s/]{0,40}EPP)")
MAPA = {"I": "I – Trabalhista", "1": "I – Trabalhista", "II": "II – Garantia real", "2": "II – Garantia real",
        "III": "III – Quirografário", "3": "III – Quirografário", "IV": "IV – ME/EPP", "4": "IV – ME/EPP"}
RX_VALOR = re.compile(r"(R\$|US\$|USD|EUR|€)\s*(-?\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})")
RX_DOC = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}|\d{3}\.?\d{3}\.?\d{3}-?\d{2}")
RX_TOTAL = re.compile(r"\b(TOTAL|SUBTOTAL|SOMA)\b")
MOEDA = {"R$": "BRL", "US$": "USD", "USD": "USD", "€": "EUR", "EUR": "EUR"}
BANCOS = [  # raiz CNPJ, nome, tipo, padrão de nome (ampliável)
    ("00000000", "Banco do Brasil", "Público", r"BANCO DO BRASIL"), ("00360305", "CAIXA", "Público", r"CAIXA ECONOMICA"),
    ("33657248", "BNDES", "Público", r"BNDES|BANCO NACIONAL DE DESENVOLVIMENTO"), ("07237373", "Banco do Nordeste", "Público", r"BANCO DO NORDESTE"),
    ("04902979", "Banco da Amazônia", "Público", r"BANCO DA AMAZONIA"), ("92702067", "Banrisul", "Público", r"BANRISUL|BANCO DO ESTADO DO RIO GRANDE DO SUL"),
    ("60746948", "Bradesco", "Privado", r"BRADESCO"), ("60701190", "Itaú Unibanco", "Privado", r"ITAU"), ("90400888", "Santander", "Privado", r"SANTANDER"),
    ("30306294", "BTG Pactual", "Privado", r"\bBTG\b"), ("58160789", "Safra", "Privado", r"SAFRA"), ("62232889", "Daycoval", "Privado", r"DAYCOVAL"),
    ("28195667", "ABC Brasil", "Privado", r"BANCO ABC"), ("59588111", "Banco BV", "Privado", r"VOTORANTIM|BANCO BV"),
    ("01181521", "Sicredi", "Cooperativo", r"SICREDI"), ("02038232", "Sicoob", "Cooperativo", r"SICOOB|BANCOOB"), ("10398952", "Cresol", "Cooperativo", r"CRESOL")]
_BRX = [(re.compile(p), n, t) for _, n, t, p in BANCOS]
_BRAIZ = {r: (n, t) for r, n, t, _ in BANCOS}


def sa(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper()


def dig(x):
    return re.sub(r"\D", "", str(x or ""))


def limpar(t):
    t = html.unescape(re.sub(r"<br\s*/?>|</p>|</tr>|</li>", "\n", t or "", flags=re.I))
    t = re.sub(r"</t[dh]>", " | ", t, flags=re.I); t = re.sub(r"<[^>]+>", " ", t).replace("\xa0", " ")
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", t)).strip()


def tipo_edital(tu):
    if "QUADRO GERAL DE CREDORES" in tu: return "QGC (art. 18)", 3
    if re.search(r"ART\.?\s*7.{0,6}2", tu) or ("ADMINISTRADOR JUDICIAL" in tu and "RELACAO DE CREDORES" in tu): return "Lista do AJ (art. 7º §2º)", 2
    if re.search(r"ART\.?\s*52.{0,6}1", tu) or "RELACAO NOMINAL DE CREDORES" in tu: return "Lista do devedor (art. 52 §1º)", 1
    if "RECUPERACAO EXTRAJUDICIAL" in tu and "CREDOR" in tu: return "RE – relação de credores", 1
    return "Outro/aviso", 0


def _classe(m):
    if m.group(1): return MAPA[m.group(1)]
    g = m.group(3)
    return "I – Trabalhista" if "TRABALH" in g else "II – Garantia real" if "GARANTIA" in g else "III – Quirografário" if "QUIROG" in g else "IV – ME/EPP"


def banco_de(nome, doc):
    if doc and doc[:8] in _BRAIZ: return _BRAIZ[doc[:8]] + ("CNPJ",)
    n = sa(nome or "")
    for rx, b, t in _BRX:
        if rx.search(n): return b, t, "nome"
    if re.search(r"\bBANCO\b|\bBANK\b|FINANCEIRA|COOPERATIVA DE CREDITO|\bFIDC\b|SECURITIZ", n):
        return "Outra instituição financeira", "Outro", "nome"
    return None, None, None


_banco = banco_de  # compatibilidade


def _itens(trecho, classe):
    out, tot = [], None
    for linha in re.split(r"\n|;(?=\s*\D)", trecho):
        vs = RX_VALOR.findall(linha)
        if not vs: continue
        moeda, val = vs[-1]; v = float(val.replace(".", "").replace(",", "."))
        if RX_TOTAL.search(sa(linha)): tot = v; continue
        d = RX_DOC.search(linha); doc = dig(d.group()) if d else ""
        nome = RX_DOC.sub(" ", linha[:RX_VALOR.search(linha).start()])
        nome = re.sub(r"(CNPJ|CPF|INSCRITO|SOB|N[ºO°]\.?|\||–|-|:|\(|\))", " ", nome, flags=re.I)
        nome = re.sub(r"^\s*\d+[\.\)]?\s+", "", re.sub(r"\s+", " ", nome)).strip(" ,.")
        if len(nome) < 3: continue
        pf = len(doc) == 11 or (classe.startswith("I –") and len(doc) != 14)
        b = banco_de(nome, doc) if not pf else (None, None, None)
        out.append(dict(classe=classe, credor="PESSOA FÍSICA" if pf else nome.upper()[:150], doc="" if pf else doc,
                        tipo_pessoa="PF" if pf else ("PJ" if len(doc) == 14 else "ND"), moeda=MOEDA[moeda], valor=v,
                        banco=b[0], tipo_banco=b[1], match_banco=b[2]))
    return out, tot


def extrair(texto):
    t = limpar(texto); tu = sa(t); tipo, prec = tipo_edital(tu)
    ms = [m for m in RX_CLASSE.finditer(tu) if not re.search(r"(TOTAL|SUBTOTAL|SOMA)\W{0,3}(DA|DE)?\W{0,3}$", tu[max(0, m.start() - 16):m.start()])]
    lin, tots = [], {}
    for i, m in enumerate(ms):
        cl = _classe(m); it, tot = _itens(t[m.end():(ms[i + 1].start() if i + 1 < len(ms) else len(t))], cl); lin += it
        if tot is not None: tots[cl] = tot
    if not ms:
        lin, _ = _itens(t, "Não informada")
    cab = t[:ms[0].start()] if ms else t[:1500]
    return tipo, prec, lin, tots, tu, cab


def processar(bruto):
    eds, vistos = [], set()
    for x in bruto:
        idp = str(x.get("id") or (x.get("numero_processo"), x.get("data_disponibilizacao")))
        if idp in vistos: continue
        vistos.add(idp)
        tipo, prec, lin, tots, tu, cab = extrair(x.get("texto") or "")
        soma = {}
        for l in lin:
            if l["moeda"] == "BRL": soma[l["classe"]] = soma.get(l["classe"], 0) + l["valor"]
        div = {c: round(abs(soma.get(c, 0) - v) / v * 100, 2) for c, v in tots.items() if v}
        conf = "Alta" if lin and div and max(div.values()) <= 1 else "Média" if len(lin) >= 3 else "Baixa" if lin else "Sem lista"
        eds.append(dict(id=idp, processo=dig(x.get("numero_processo")), tribunal=x.get("siglaTribunal"), data=x.get("data_disponibilizacao"),
                        tipo_edital=tipo, precedencia=prec, rj_re="RE" if "EXTRAJUDICIAL" in tu else "RJ",
                        devedora=";".join(d.get("nome", "") for d in (x.get("destinatarios") or []) if isinstance(d, dict))[:300],
                        cnpjs_devedora=";".join(sorted({dig(c) for c in RX_DOC.findall(cab) if len(dig(c)) == 14}))[:300],
                        n_credores=len(lin), valor_extraido=round(sum(soma.values()), 2), totais=str(tots), divergencia=str(div), confianca=conf,
                        lista_em_anexo=int(bool(re.search(r"ANEXO|DISPONIVEL NO SITE|ACESSE|WWW\.", tu)) and not lin), link=x.get("link"), _lin=lin))
    vig = {}
    for e in eds:
        if e["n_credores"] and (e["processo"] not in vig or (e["precedencia"], e["data"] or "") > (vig[e["processo"]]["precedencia"], vig[e["processo"]]["data"] or "")):
            vig[e["processo"]] = e
    n = 0
    with ana() as c:
        for e in eds:
            lin = e.pop("_lin"); e["vigente"] = int(vig.get(e["processo"]) is e)
            c.execute("INSERT OR REPLACE INTO djen_editais(id,processo,tribunal,data,tipo_edital,precedencia,rj_re,devedora,cnpjs_devedora,n_credores,"
                      "valor_extraido,totais,divergencia,confianca,lista_em_anexo,vigente,link) VALUES(:id,:processo,:tribunal,:data,:tipo_edital,:precedencia,"
                      ":rj_re,:devedora,:cnpjs_devedora,:n_credores,:valor_extraido,:totais,:divergencia,:confianca,:lista_em_anexo,:vigente,:link)", e)
            if e["vigente"]:
                c.execute("UPDATE djen_editais SET vigente=0 WHERE processo=? AND id<>?", (e["processo"], e["id"]))
                c.execute("DELETE FROM credores WHERE processo=?", (e["processo"],))
                for l in lin:
                    c.execute("INSERT INTO credores(edital_id,processo,classe,credor,doc,tipo_pessoa,moeda,valor,banco,tipo_banco,match_banco) "
                              "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (e["id"], e["processo"], l["classe"], l["credor"], l["doc"], l["tipo_pessoa"],
                                                                l["moeda"], l["valor"], l["banco"], l["tipo_banco"], l["match_banco"])); n += 1
    return n, f"{len(eds)} editais, {len(vig)} vigentes, {n} credores"
