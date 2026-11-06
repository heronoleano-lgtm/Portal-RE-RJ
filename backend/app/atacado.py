"""Leitura da base de clientes do Atacado (DB5186) SEM openpyxl/pandas: o .xlsx é um ZIP de XML.
Dado sensível (sigilo bancário / LGPD): fica só em dados/analitico.db; acesso exige permissão 'carteira';
indisponível na edição pública."""
import datetime as dt, re, zipfile, logging, xml.etree.ElementTree as ET
from .db import ana

log = logging.getLogger("motor.atacado")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REG = {"Norte": "AC AM AP PA RO RR TO", "Nordeste": "AL BA CE MA PB PE PI RN SE", "Centro-Oeste": "DF GO MS MT", "Sudeste": "ES MG RJ SP", "Sul": "PR RS SC"}
UF2REG = {u: r for r, us in REG.items() for u in us.split()}
ALIAS = {"cnpj": ["CO_CNPJ", "NU_CNPJ"], "unidade": ["NU_UNIDADE"], "carteira": ["CO_CARTEIRA"], "razao": ["NO_RAZAO_SOCIAL"],
         "segmento": ["CO_CARTEIRA_SICLI", "CO_SEGMENTO_SICLI"], "cnae": ["CO_CNAE"], "faturamento": ["VR_FATURAMENTO"], "uf": ["CO_UF"],
         "municipio": ["NO_MUNICIPIO"], "raiz_grupo": ["CO_CNPJ_BASE_GRUPO", "NU_CNPJ_BASE_GRUPO"], "dt_fat": ["DT_FATURAMENTO"]}


def _col(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def ler_xlsx(caminho):
    z = zipfile.ZipFile(caminho)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for _, el in ET.iterparse(z.open("xl/sharedStrings.xml")):
            if el.tag == NS + "si":
                ss.append("".join(t.text or "" for t in el.iter(NS + "t"))); el.clear()
    planilha = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))[0]
    cab = None
    for _, el in ET.iterparse(z.open(planilha)):
        if el.tag != NS + "row":
            continue
        lin = {}
        for c in el.iter(NS + "c"):
            v = c.find(NS + "v"); t = c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(NS + "t"))
            elif v is None:
                val = ""
            elif t == "s":
                val = ss[int(v.text)]
            else:
                val = v.text or ""
            lin[_col(c.get("r"))] = val
        el.clear()
        linha = [lin.get(i, "") for i in range(max(lin) + 1)] if lin else []
        if cab is None:
            cab = [x.strip().upper() for x in linha]; continue
        yield dict(zip(cab, linha))


def _setor(cnae):
    try:
        d = int(str(cnae).zfill(7)[:2])
    except ValueError:
        return "Não identificado"
    return ("Agropecuária" if d <= 3 else "Extrativa" if d <= 9 else "Indústria" if d <= 33 else "Energia" if d == 35 else
            "Saneamento/Resíduos" if d <= 39 else "Construção" if d <= 43 else "Comércio" if d <= 47 else "Transporte/Logística" if d <= 53 else
            "Financeiras/Holdings" if 64 <= d <= 66 else "Imobiliário" if d == 68 else "Serviços")


def _num(x):
    x = str(x).strip()
    if not x:
        return None
    if "," in x:
        x = x.replace(".", "").replace(",", ".")
    try:
        return float(x)
    except ValueError:
        return None


def _ano(x):
    x = str(x).strip()
    if re.fullmatch(r"\d+(\.\d+)?", x):
        try:
            return (dt.date(1899, 12, 30) + dt.timedelta(days=int(float(x)))).year
        except OverflowError:
            return None
    m = re.match(r"(\d{4})", x)
    return int(m.group(1)) if m else None


def _faixa(f):
    if f is None or f <= 0: return "Não informado/zero"
    return "até 4,8 mi" if f <= 4.8e6 else "4,8–300 mi" if f <= 3e8 else "300 mi–1 bi" if f <= 1e9 else "1–5 bi" if f <= 5e9 else "> 5 bi"


def importar(caminho):
    ano_corte = dt.date.today().year - 2
    n = 0
    with ana() as c:
        c.execute("DELETE FROM carteira")
        for r in ler_xlsx(caminho):
            g = lambda k: next((r[a] for a in ALIAS[k] if a in r), "")
            cnpj = re.sub(r"\D", "", g("cnpj")).zfill(14)
            if cnpj == "0" * 14:
                continue
            razao = g("razao"); ru = razao.upper(); fat = _num(g("faturamento")); ano = _ano(g("dt_fat"))
            sit = ("Falência" if re.search(r"FALID|MASSA\s+FAL|FAL[EÊ]NCIA", ru) else "RJ" if re.search(r"RECUPERA[CÇ][AÃ]O\s+JUDICIAL", ru)
                   else "RE" if re.search(r"RECUPERA[CÇ][AÃ]O\s+EXTRAJUDICIAL", ru) else "Liquidação" if re.search(r"LIQUIDA[CÇ][AÃ]O", ru) else "Sem indicação")
            qual = ("Faturamento zero/ausente" if not fat or fat <= 0 else "Data 1899 (sentinela)" if ano == 1899
                    else "Faturamento > 2 anos" if (ano is None or ano < ano_corte) else "OK")
            seg = g("segmento") or "NA"; uf = g("uf").upper()
            rg = re.sub(r"\D", "", g("raiz_grupo")).zfill(8)
            c.execute("INSERT OR REPLACE INTO carteira(cnpj,raiz,raiz_grupo,razao,unidade,carteira,segmento,seg2,cnae,setor,faturamento,faixa_fat,uf,regiao,"
                      "municipio,ano_fat,qualidade,situacao_nome,f_razao) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (cnpj, cnpj[:8], cnpj[:8] if rg == "00000000" else rg, razao, g("unidade"), g("carteira"), seg, seg[:2], g("cnae"), _setor(g("cnae")),
                       fat, _faixa(fat), uf, UF2REG.get(uf, "Exterior/NI"), g("municipio"), ano, qual, sit, int(sit != "Sem indicação")))
            n += 1
    atualizar_status()
    log.info("Atacado importado: %s CNPJs", n)
    return n


def atualizar_status():
    """Cruza a carteira com as partes identificadas (DJEN/editais) e com a CVM; marca grupos afetados e contágio."""
    with ana() as c:
        raizes_djen = {r[0] for r in c.execute("SELECT DISTINCT raiz FROM partes WHERE raiz IS NOT NULL AND papel IN ('devedora','citada')")}
        for (s,) in c.execute("SELECT cnpjs FROM djen_publicacoes WHERE cnpjs<>''"):
            raizes_djen |= {x[:8] for x in s.split(";") if len(x) == 14}
        raizes_cvm = {r[0][:8] for r in c.execute("SELECT cnpj FROM cvm_insolvencia")}
        c.execute("UPDATE carteira SET f_djen=0, f_cvm=0")
        for rz in raizes_djen:
            c.execute("UPDATE carteira SET f_djen=1 WHERE raiz=?", (rz,))
        for rz in raizes_cvm:
            c.execute("UPDATE carteira SET f_cvm=1 WHERE raiz=?", (rz,))
        c.execute("UPDATE carteira SET em_insolvencia = (f_razao=1 OR f_djen=1 OR f_cvm=1), em_rj = (situacao_nome='RJ' OR f_djen=1)")
        c.execute("UPDATE carteira SET grupo_afetado = raiz_grupo IN (SELECT raiz_grupo FROM carteira WHERE em_insolvencia=1)")
        c.execute("UPDATE carteira SET contagio = (grupo_afetado=1 AND em_insolvencia=0)")
