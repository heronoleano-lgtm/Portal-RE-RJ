"""Orquestração estatística (camada de aplicação). Python puro, validado contra statsmodels/SciPy (tests/).
nacional  : séries do DataJud (anual, mensal, UF, varas) e macro
macro     : correlação defasada (0–12m), Granger, GLM binomial negativo, projeção 12m em 3 cenários (Focus)
avancado  : decomposição, Holt-Winters, ensemble validado, regimes
processos : estatísticas do cruzamento (tempos processuais, vara especializada × comum, convolação, litisconsórcio, grupos, credores recorrentes)
credores  : passivo por classe e banco, HHI, Gini/Lorenz
carteira  : (edição interna) taxas por dimensão + qui², logit, contágio, clientes com processo identificado
"""
import math, json, logging, datetime as dt
from .db import ana, estat_set, estat_get
from .config import CFG
from . import analise_avancada as AA

log = logging.getLogger("motor.estat")


# ---------------- álgebra mínima ----------------
def _inv(A):
    n = len(A); M = [r[:] + [float(i == j) for j in range(n)] for i, r in enumerate(A)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(M[r][i]))
        if abs(M[p][i]) < 1e-12:
            raise ValueError("matriz singular")
        M[i], M[p] = M[p], M[i]; d = M[i][i]; M[i] = [x / d for x in M[i]]
        for r in range(n):
            if r != i and M[r][i]:
                f = M[r][i]; M[r] = [a - f * b for a, b in zip(M[r], M[i])]
    return [r[n:] for r in M]


def _irls(X, y, w0, familia, alpha=0.0, it=50):
    """GLM por IRLS. familia: 'binomial' (y = sucessos, w0 = tentativas) ou 'nb' (log, Var = mu + alpha mu²)."""
    k = len(X[0]); b = [0.0] * k
    if familia == "binomial":
        p0 = sum(y) / sum(w0); b[0] = math.log(p0 / (1 - p0))
    else:
        b[0] = math.log(max(sum(y) / len(y), 1e-6))
    for _ in range(it):
        XtWX = [[0.0] * k for _ in range(k)]; XtWz = [0.0] * k
        for xi, yi, ni in zip(X, y, w0):
            eta = sum(a * c for a, c in zip(xi, b))
            if familia == "binomial":
                mu = 1 / (1 + math.exp(-max(min(eta, 30), -30))); var = ni * mu * (1 - mu)
                if var < 1e-10: continue
                z = eta + (yi - ni * mu) / var; w = var
            else:
                mu = math.exp(min(eta, 30)); w = mu / (1 + alpha * mu); z = eta + (yi - mu) / mu
            for a in range(k):
                wa = w * xi[a]; XtWz[a] += wa * z
                for c in range(a, k):
                    XtWX[a][c] += wa * xi[c]
        for a in range(k):
            for c in range(a):
                XtWX[a][c] = XtWX[c][a]
        cov = _inv(XtWX); nb = [sum(cov[a][c] * XtWz[c] for c in range(k)) for a in range(k)]
        conv = max(abs(p - q) for p, q in zip(nb, b)) < 1e-8; b = nb
        if conv: break
    ep = [math.sqrt(max(cov[i][i], 0)) for i in range(k)]
    return b, ep, cov


def _phi(z):
    return 0.5 * math.erfc(-z / math.sqrt(2))


def _p_normal(b, ep):
    return 2 * (1 - _phi(abs(b / ep))) if ep > 0 else None


def _gammq(a, x):
    if x <= 0: return 1.0
    gln = math.lgamma(a)
    if x < a + 1:
        s = d = 1 / a; ap = a
        for _ in range(500):
            ap += 1; d *= x / ap; s += d
            if abs(d) < abs(s) * 1e-12: break
        return 1 - s * math.exp(-x + a * math.log(x) - gln)
    b = x + 1 - a; c = 1e300; d = 1 / b; h = d
    for i in range(1, 500):
        an = -i * (i - a); b += 2; d = an * d + b; d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c; c = 1e-300 if abs(c) < 1e-300 else c; d = 1 / d; de = d * c; h *= de
        if abs(de - 1) < 1e-12: break
    return math.exp(-x + a * math.log(x) - gln) * h


def p_qui2(est, gl):
    return _gammq(gl / 2, est / 2) if gl > 0 else None


def _betai(a, b, x):
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    def cf(a, b, x):
        qab, qap, qam = a + b, a + 1, a - 1; c = 1; d = 1 - qab * x / qap; d = 1 / (d if abs(d) > 1e-300 else 1e-300); h = d
        for m in range(1, 300):
            m2 = 2 * m; aa = m * (b - m) * x / ((qam + m2) * (a + m2)); d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-300 else 1e-300)
            c = 1 + aa / c; h *= d * c; aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2)); d = 1 + aa * d
            d = 1 / (d if abs(d) > 1e-300 else 1e-300); c = 1 + aa / c; de = d * c; h *= de
            if abs(de - 1) < 1e-12: break
        return h
    return bt * cf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - bt * cf(b, a, 1 - x) / b


def p_F(F, d1, d2):
    return _betai(d2 / 2, d1 / 2, d2 / (d2 + d1 * F)) if F > 0 else 1.0


def _ols_rss(X, y):
    k = len(X[0]); XtX = [[sum(r[a] * r[c] for r in X) for c in range(k)] for a in range(k)]
    Xty = [sum(r[a] * yi for r, yi in zip(X, y)) for a in range(k)]; b = [sum(i * j for i, j in zip(row, Xty)) for row in _inv(XtX)]
    return sum((yi - sum(p * q for p, q in zip(r, b))) ** 2 for r, yi in zip(X, y))


def corr(a, b):
    pares = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pares) < 12: return None
    n = len(pares); mx = sum(p[0] for p in pares) / n; my = sum(p[1] for p in pares) / n
    sx = math.sqrt(sum((p[0] - mx) ** 2 for p in pares)); sy = math.sqrt(sum((p[1] - my) ** 2 for p in pares))
    return sum((p[0] - mx) * (p[1] - my) for p in pares) / (sx * sy) if sx and sy else None


def granger(y, x, L=4):
    """H0: x não antecede y (primeiras diferenças). Retorna p-valor do teste F."""
    dy = [None] + [b - a if a is not None and b is not None else None for a, b in zip(y, y[1:])]
    dx = [None] + [b - a if a is not None and b is not None else None for a, b in zip(x, x[1:])]
    R, U, Y = [], [], []
    for t in range(L + 1, len(y)):
        lags_y = [dy[t - i] for i in range(1, L + 1)]; lags_x = [dx[t - i] for i in range(1, L + 1)]
        if dy[t] is None or None in lags_y or None in lags_x: continue
        R.append([1.0] + lags_y); U.append([1.0] + lags_y + lags_x); Y.append(dy[t])
    if len(Y) < 3 * (2 * L + 1): return None
    try:
        rr, ru = _ols_rss(R, Y), _ols_rss(U, Y)
    except ValueError:
        return None
    d2 = len(Y) - (2 * L + 1); F = ((rr - ru) / L) / (ru / d2) if ru > 0 else 0
    return p_F(F, L, d2)


# ---------------- nacional e macro ----------------
def _serie_meses(inicio, fim):
    a, m = map(int, inicio.split("-")); out = []
    while f"{a:04d}-{m:02d}" <= fim:
        out.append(f"{a:04d}-{m:02d}"); m += 1
        if m > 12: a, m = a + 1, 1
    return out


def nacional():
    with ana() as c:
        estat_set("nacional", {
            "anual": [dict(r) for r in c.execute("SELECT substr(mes,1,4) ano, tipo, SUM(qtd) qtd FROM datajud_mensal GROUP BY 1,2 ORDER BY 1")],
            "mensal_rj": [dict(r) for r in c.execute("SELECT mes, SUM(qtd) qtd FROM datajud_mensal WHERE tipo='RJ' GROUP BY mes ORDER BY mes")],
            "uf_rj": [dict(r) for r in c.execute("SELECT uf, SUM(qtd) qtd FROM datajud_mensal WHERE tipo='RJ' GROUP BY uf ORDER BY qtd DESC")],
            "varas": [dict(r) for r in c.execute("SELECT orgao, tribunal, qtd FROM datajud_varas WHERE tipo='RJ' ORDER BY qtd DESC LIMIT 15")],
            "macro": [dict(r) for r in c.execute("SELECT serie, mes, valor FROM macro_mensal WHERE serie IN ('selic_meta','juros_pj_livres','spread_pj_livres','inadimpl_pj_total') ORDER BY mes")],
            "curva": [dict(r) for r in c.execute("SELECT momento, curva, prazo, taxa FROM curva ORDER BY momento, curva, prazo")],
            "focus": [dict(r) for r in c.execute("SELECT * FROM focus ORDER BY indicador, ref")]})


def macro():
    with ana() as c:
        rj = {r[0]: r[1] for r in c.execute("SELECT mes, SUM(qtd) FROM datajud_mensal WHERE tipo='RJ' GROUP BY mes")}
        if len(rj) < 36:
            estat_set("macro_status", "Série de RJ insuficiente – execute a coleta DataJud."); return
        meses = _serie_meses(min(rj), max(rj))
        ms = {}
        for s, m, v in c.execute("SELECT serie, mes, valor FROM macro_mensal"):
            ms.setdefault(s, {})[m] = v
        for m, pc, pl, jr, inc in c.execute("SELECT * FROM curva_mensal"):
            for k, v in (("pre_curto", pc), ("pre_longo", pl), ("juro_real_5a", jr), ("inclinacao_pre", inc)):
                ms.setdefault(k, {})[m] = v
        focus = {(r[0], r[1]): r[2] for r in c.execute("SELECT indicador, ref, mediana FROM focus")}
    y = [rj.get(m, 0) for m in meses]
    X = {}
    for s, d in ms.items():
        v = [d.get(m) for m in meses]
        if s in ("cambio_usd", "ibc_br_dessaz", "saldo_credito_pj", "concessoes_pj_livres"):
            v = [None] * 12 + [(b / a - 1) * 100 if a and b is not None else None for a, b in zip(v, v[12:])]; s += "_var12m"
        X[s] = v
    if "ipca_mensal" in X:
        ip = X.pop("ipca_mensal"); acc = [None] * 11
        for i in range(11, len(ip)):
            jan = ip[i - 11:i + 1]
            acc.append((math.prod(1 + p / 100 for p in jan) - 1) * 100 if None not in jan else None)
        X["ipca_12m"] = acc
        if "selic_meta" in X:
            X["juro_real_ex_post"] = [s - i if s is not None and i is not None else None for s, i in zip(X["selic_meta"], acc)]
    res = []
    for nome, v in X.items():
        melhor = None
        for k in range(0, 13):
            r = corr(y[k:], v[:len(v) - k] if k else v)
            if r is not None and (melhor is None or abs(r) > abs(melhor[1])): melhor = (k, r)
        if melhor:
            pg = granger(y, v)
            res.append({"variavel": nome, "defasagem_meses": melhor[0], "correlacao": round(melhor[1], 3),
                        "granger_p": round(pg, 4) if pg is not None else None, "antecede_rj": bool(pg is not None and pg < 0.05)})
    res.sort(key=lambda r: -abs(r["correlacao"]))
    estat_set("macro_correlacoes", res)
    fam = [["selic_meta", "juros_pj_livres", "pre_curto", "pre_longo", "juro_real_5a", "juro_real_ex_post"], ["spread_pj_livres", "inclinacao_pre"],
           ["concessoes_pj_livres_var12m", "saldo_credito_pj_var12m"], ["inadimpl_pj_total"], ["ibc_br_dessaz_var12m", "desemprego_pnad"], ["cambio_usd_var12m"]]
    sel = []
    for f in fam:
        cand = [r for r in res if r["variavel"] in f]
        if cand: sel.append(cand[0])
    sel = sorted(sel, key=lambda r: -abs(r["correlacao"]))[:4]
    def lag(v, k): return [None] * k + v[:len(v) - k] if k else v
    final = []
    for nv, k in [(r["variavel"], r["defasagem_meses"]) for r in sel]:
        if all(abs(corr(lag(X[nv], k), lag(X[o], ko)) or 0) <= 0.85 for o, ko in final): final.append((nv, k))
    linhas = []
    for t in range(len(meses)):
        xs = [lag(X[nv], k)[t] for nv, k in final]
        if None not in xs: linhas.append(([1.0] + xs + [t / 12], y[t]))
    if len(linhas) < 30:
        estat_set("macro_status", "Variáveis macro insuficientes – execute a coleta macro."); return
    Xm = [l[0] for l in linhas]; ym = [l[1] for l in linhas]; mu = sum(ym) / len(ym); var = sum((v - mu) ** 2 for v in ym) / (len(ym) - 1)
    alpha = max(1e-3, (var - mu) / mu ** 2)
    b, ep, cov = _irls(Xm, ym, [1] * len(ym), "nb", alpha)
    nomes = ["constante"] + [f"{nv} (defasagem {k}m)" for nv, k in final] + ["tendência (ano)"]
    tab = [{"termo": n, "coef": round(bi, 4), "efeito_%": round((math.exp(bi) - 1) * 100, 2) if 0 < i < len(nomes) - 1 else None,
            "p_valor": round(_p_normal(bi, e), 4) if e else None} for i, (n, bi, e) in enumerate(zip(nomes, b, ep))]
    def dev(yv, m): return 2 * sum((yi * math.log(yi / mi) if yi > 0 else 0) - (yi + 1 / alpha) * math.log((1 + alpha * yi) / (1 + alpha * mi)) for yi, mi in zip(yv, m))
    mu_hat = [math.exp(sum(a * c for a, c in zip(x, b))) for x in Xm]
    pseudo = 1 - dev(ym, mu_hat) / dev(ym, [mu] * len(ym))
    estat_set("macro_modelo", {"tabela": tab, "pseudo_r2": round(pseudo, 3), "n_meses": len(ym), "alpha": round(alpha, 4)})
    ult = {nv: next((v for v in reversed(X[nv]) if v is not None), None) for nv, _ in final}
    selic_fut = {r: v for (ind, r), v in focus.items() if ind == "Selic"}
    proj = []
    for cen, dj, di in (("Base (Focus)", 0, 0), ("Estresse (+200 bps; +2 p.p. inadimplência)", 2, 2), ("Alívio (-200 bps)", -2, 0)):
        for h in range(1, 13):
            t = len(meses) - 1 + h; xs = [1.0]
            for nv, k in final:
                idx = t - k
                if idx < len(meses):
                    v = X[nv][idx]
                else:
                    v = ult[nv]
                    if nv in ("selic_meta", "juros_pj_livres", "pre_curto", "pre_longo", "juro_real_ex_post"):
                        ano = str(int(meses[-1][:4]) + (1 if h > 12 - int(meses[-1][5:]) else 0))
                        if nv == "selic_meta" and ano in selic_fut: v = selic_fut[ano]
                        v = (v or 0) + dj
                    if nv == "inadimpl_pj_total": v = (v or 0) + di
                xs.append(v if v is not None else 0)
            xs.append(t / 12)
            eta = sum(a * c for a, c in zip(xs, b)); se = math.sqrt(max(sum(xs[i] * cov[i][j] * xs[j] for i in range(len(xs)) for j in range(len(xs))), 0))
            a, m = map(int, meses[-1].split("-")); m += h; a += (m - 1) // 12; m = (m - 1) % 12 + 1
            proj.append({"mes": f"{a:04d}-{m:02d}", "cenario": cen, "previsto": round(math.exp(eta), 1),
                         "ic80_inf": round(math.exp(eta - 1.2816 * se), 1), "ic80_sup": round(math.exp(eta + 1.2816 * se), 1)})
    estat_set("macro_projecao", proj); estat_set("macro_status", "ok")


# ---------------- tendência e previsão ----------------
def _nb_sazonal(treino, h):
    """GLM binomial negativo com tendência e dummies mensais."""
    n = len(treino)
    X = [[1.0, t / 12] + [float(t % 12 == k) for k in range(1, 12)] for t in range(n)]
    mu = sum(treino) / n; var = sum((v - mu) ** 2 for v in treino) / max(n - 1, 1)
    alpha = max(1e-3, (var - mu) / mu ** 2)
    b, _, cov = _irls(X, treino, [1] * n, "nb", alpha)
    out = []
    for k in range(h):
        t = n + k; x = [1.0, t / 12] + [float(t % 12 == j) for j in range(1, 12)]
        eta = sum(p * q for p, q in zip(x, b)); se = math.sqrt(max(sum(x[i] * cov[i][j] * x[j] for i in range(len(x)) for j in range(len(x))), 0))
        sd_tot = math.sqrt(se ** 2 + math.log(1 + alpha + 1 / max(math.exp(eta), 1e-6)))
        out.append({"previsto": math.exp(eta), "inf": math.exp(eta - 1.2816 * sd_tot), "sup": math.exp(eta + 1.2816 * sd_tot)})
    return out


def avancado():
    with ana() as c:
        serie = [(r[0], r[1]) for r in c.execute("SELECT mes, SUM(qtd) FROM datajud_mensal WHERE tipo='RJ' GROUP BY mes ORDER BY mes")]
    if len(serie) < 48:
        estat_set("avancado", None); return
    serie = serie[:-1] if serie and serie[-1][0] >= dt.date.today().strftime("%Y-%m") else serie  # mês corrente é parcial
    meses = [m for m, _ in serie]; y = [float(v) for _, v in serie]
    dec = AA.decompor(y)
    hw = AA.holt_winters(y, 12)
    prev = {"Holt-Winters": lambda tr, h: [p["previsto"] for p in AA.holt_winters(tr, h)["previsao"]],
            "Binomial negativo sazonal": lambda tr, h: [p["previsto"] for p in _nb_sazonal(tr, h)],
            "Ingênuo sazonal": AA.ingenuo_sazonal}
    cv = AA.validacao_cruzada(y, prev)
    cand = {"Holt-Winters": [{"previsto": p["previsto"], "inf": p["inf"], "sup": p["sup"]} for p in hw["previsao"]] if hw else None,
            "Binomial negativo sazonal": _nb_sazonal(y, 12)}
    d12 = [y[t] - y[t - 12] for t in range(12, len(y))]; sd12 = (sum(v * v for v in d12) / len(d12)) ** 0.5
    cand["Ingênuo sazonal"] = [{"previsto": v, "inf": max(v - 1.2816 * sd12, 0), "sup": v + 1.2816 * sd12} for v in AA.ingenuo_sazonal(y, 12)]
    cand = {k: v for k, v in cand.items() if v}
    ens, pesos = AA.ensemble(cand, cv or {})
    a, m = map(int, meses[-1].split("-"))
    fut = []
    for k in range(1, 13):
        mm = m + k; fut.append(f"{a + (mm - 1) // 12:04d}-{(mm - 1) % 12 + 1:02d}")
    q = AA.pontos_de_quebra([int(v) for v in y])
    for r in q["regimes"]:
        r["de"], r["ate"] = meses[r["inicio"]], meses[r["fim"]]
    ult12, ant12 = sum(y[-12:]), sum(y[-24:-12])
    estat_set("avancado", {
        "meses": meses, "observado": y,
        "tendencia": [round(v, 2) for v in dec["tendencia"]] if dec else None,
        "indices_sazonais": [round(v, 3) for v in dec["indices"]] if dec else None,
        "previsao_meses": fut,
        "previsao_ensemble": [{k: round(v, 1) for k, v in p.items()} for p in (ens or [])],
        "previsao_modelos": {k: [round(p["previsto"], 1) for p in v] for k, v in cand.items()},
        "pesos_ensemble": pesos, "validacao": cv, "holt_winters": hw["parametros"] if hw else None,
        "regimes": q["regimes"],
        "variacao_12m_%": round((ult12 / ant12 - 1) * 100, 1) if ant12 else None,
        "acumulado_12m": int(ult12)})


# ---------------- processos (resultado do cruzamento) ----------------
def processos():
    with ana() as c:
        P = [dict(r) for r in c.execute("SELECT * FROM processos")]
        g = [dict(r) for r in c.execute("SELECT * FROM grupos WHERE n_empresas>1 OR n_processos>1 ORDER BY n_empresas DESC, n_processos DESC LIMIT 50")]
        bancos = [dict(r) for r in c.execute("""SELECT banco, COUNT(DISTINCT processo) processos, SUM(valor) valor FROM partes
                                                WHERE papel='credora' AND banco IS NOT NULL GROUP BY banco ORDER BY processos DESC, valor DESC""")]
        papeis = [dict(r) for r in c.execute("SELECT papel, fonte, COUNT(*) n, COUNT(DISTINCT raiz) empresas FROM partes GROUP BY papel, fonte")]
        recorrentes = [dict(r) for r in c.execute("""SELECT raiz, MAX(nome) nome, COUNT(DISTINCT processo) processos FROM partes
                                                     WHERE papel='devedora' AND raiz IS NOT NULL GROUP BY raiz HAVING COUNT(DISTINCT processo)>1
                                                     ORDER BY processos DESC LIMIT 30""")]
        cvm = [dict(r) for r in c.execute("""SELECT p.processo, p.tribunal, p.tipo, pa.nome, pa.cvm_situacao FROM partes pa JOIN processos p ON p.processo=pa.processo
                                             WHERE pa.cvm_situacao IS NOT NULL GROUP BY p.processo, pa.raiz LIMIT 50""")]
        ign = c.execute("SELECT COUNT(*) FROM datajud_processos WHERE encontrado=0").fetchone()[0]
    if not P:
        estat_set("processos", None); return
    cont = lambda chave: sorted(({"categoria": k, "processos": v} for k, v in _conta(P, chave).items()), key=lambda x: -x["processos"])
    com_dj = [p for p in P if "DataJud" in (p["fontes"] or "")]
    dd = [p["dias_deferimento"] for p in P if p["dias_deferimento"] is not None]
    por_uf = {}
    for p in P:
        if p["dias_deferimento"] is not None and p["uf"]:
            por_uf.setdefault(p["uf"], []).append(p["dias_deferimento"])
    tempos_uf = sorted(({"uf": u, "mediana_dias": AA.mediana(v), "processos": len(v)} for u, v in por_uf.items() if len(v) >= 5), key=lambda x: x["mediana_dias"])
    esp = [p["dias_deferimento"] for p in P if p["vara_especializada"] == 1 and p["dias_deferimento"] is not None]
    com = [p["dias_deferimento"] for p in P if p["vara_especializada"] == 0 and p["dias_deferimento"] is not None]
    _, pmw = AA.mann_whitney(esp, com)
    hoje = dt.date.today().isoformat()
    dur, ev = [], []
    for p in P:
        if p["tipo"] == "RJ" and p["ajuizamento"] and p["convolada"] is not None:
            fim = p["dt_convolacao"] or p["dt_ultima_mov"] or hoje
            try:
                d = (dt.date.fromisoformat(fim[:10]) - dt.date.fromisoformat(p["ajuizamento"][:10])).days
            except ValueError:
                continue
            if d >= 0:
                dur.append(d); ev.append(1 if p["convolada"] else 0)
    km = AA.kaplan_meier(dur, ev)
    com_dev = [p for p in P if p["n_raizes"]]
    estat_set("processos", {
        "total": len(P), "com_datajud": len(com_dj), "nao_localizados_datajud": ign,
        "com_edital": sum(1 for p in P if "Edital" in (p["fontes"] or "")),
        "por_tipo": cont("tipo"), "por_tribunal": cont("tribunal")[:15], "por_uf": cont("uf"),
        "tempo_deferimento": {"mediana": AA.mediana(dd), "n": len(dd), "por_uf": tempos_uf,
                              "especializada": {"mediana": AA.mediana(esp), "n": len(esp)}, "comum": {"mediana": AA.mediana(com), "n": len(com)},
                              "mann_whitney_p": round(pmw, 4) if pmw is not None else None},
        "convolacao": {"convoladas": sum(1 for p in P if p["convolada"]), "base": sum(1 for p in P if p["convolada"] is not None), "km": km},
        "litisconsorcio": {"processos_com_devedora": len(com_dev), "mais_de_uma_empresa": sum(1 for p in com_dev if p["n_raizes"] > 1)},
        "grupos": g, "recorrentes": recorrentes, "bancos_recorrentes": bancos[:15], "partes_por_papel": papeis, "companhias_abertas": cvm,
        "lista": sorted(({k: p[k] for k in ("processo", "tribunal", "uf", "tipo", "ajuizamento", "orgao", "devedora", "partes_citadas", "n_devedoras",
                                            "passivo", "n_credores", "bancos_pct", "dias_deferimento", "convolada", "cvm", "fontes", "ultima_pub")} for p in P),
                        key=lambda x: (x["ultima_pub"] or ""), reverse=True)[:500]})


def _conta(linhas, chave):
    out = {}
    for l in linhas:
        k = l.get(chave) or "Não informado"
        out[k] = out.get(k, 0) + 1
    return out


# ---------------- credores e concentração ----------------
def credores():
    with ana() as c:
        porc = [dict(r) for r in c.execute("""SELECT e.processo, e.tribunal, e.rj_re, e.devedora, e.cnpjs_devedora, e.confianca, e.tipo_edital,
              SUM(CASE WHEN k.moeda='BRL' THEN k.valor END) passivo, SUM(CASE WHEN k.moeda='BRL' AND k.banco IS NOT NULL THEN k.valor END) bancos,
              SUM(CASE WHEN k.moeda='BRL' AND k.banco='CAIXA' THEN k.valor END) caixa
              FROM djen_editais e JOIN credores k ON k.edital_id=e.id WHERE e.vigente=1 GROUP BY e.processo ORDER BY passivo DESC""")]
        classe = [dict(r) for r in c.execute("SELECT classe, SUM(valor) valor, COUNT(*) credores FROM credores WHERE moeda='BRL' GROUP BY classe")]
        bancos = [dict(r) for r in c.execute("""SELECT banco, tipo_banco, classe, SUM(valor) valor, COUNT(DISTINCT processo) processos FROM credores
              WHERE moeda='BRL' AND banco IS NOT NULL GROUP BY banco, tipo_banco, classe ORDER BY valor DESC""")]
        conf = {r[0]: r[1] for r in c.execute("SELECT confianca, COUNT(*) FROM djen_editais GROUP BY confianca")}
        anexos = c.execute("SELECT COUNT(*) FROM djen_editais WHERE lista_em_anexo=1").fetchone()[0]
        nomes = {r[0]: r[1] for r in c.execute("SELECT processo, devedora FROM processos")}
        rz = {r[0] for r in c.execute("SELECT raiz FROM carteira")}
    for p in porc:
        p["devedora"] = nomes.get(p["processo"]) or None  # nome confirmado pelo cruzamento (cabeçalho do edital)
        p["bancos_%"] = round((p["bancos"] or 0) / p["passivo"] * 100, 2) if p["passivo"] else None
        p["caixa_%"] = round((p["caixa"] or 0) / p["passivo"] * 100, 2) if p["passivo"] else None
        p["cliente_atacado"] = any(x[:8] in rz for x in (p.pop("cnpjs_devedora") or "").split(";") if x)
    estat_set("credores", {"processos": porc[:500], "classes": classe, "bancos": bancos, "confianca": conf, "lista_em_anexo": anexos})


def concentracao_credores():
    with ana() as c:
        porp = {}
        for proc, banco, valor in c.execute("""SELECT k.processo, k.banco, SUM(k.valor) FROM credores k JOIN djen_editais e ON e.id=k.edital_id
                                               WHERE e.vigente=1 AND k.moeda='BRL' GROUP BY k.processo, k.banco"""):
            porp.setdefault(proc, {"bancos": [], "total": 0.0})
            porp[proc]["total"] += valor or 0
            if banco:
                porp[proc]["bancos"].append(valor or 0)
        agreg = [r[1] for r in c.execute("SELECT banco, SUM(valor) FROM credores WHERE moeda='BRL' AND banco IS NOT NULL GROUP BY banco")]
    passivos = [v["total"] for v in porp.values() if v["total"] > 0]
    hhis = [h for h in (AA.hhi(v["bancos"]) for v in porp.values() if v["bancos"]) if h is not None]
    estat_set("concentracao", {
        "gini_passivo": AA.gini(passivos), "lorenz_passivo": AA.lorenz(passivos),
        "hhi_bancos_agregado": AA.hhi(agreg), "faixa_agregado": AA.faixa_hhi(AA.hhi(agreg)),
        "hhi_mediano_processo": AA.mediana(hhis),
        "distribuicao_hhi": {f: sum(1 for h in hhis if AA.faixa_hhi(h) == f) for f in ("baixa", "moderada", "alta")},
        "processos": len(passivos)})


# ---------------- carteira (edição interna) ----------------
DIMS = ["seg2", "segmento", "carteira", "setor", "faixa_fat", "regiao", "uf", "unidade", "qualidade"]


def carteira():
    with ana() as c:
        tot = c.execute("SELECT COUNT(*), SUM(em_insolvencia), SUM(em_rj), SUM(situacao_nome='Falência'), COUNT(DISTINCT raiz_grupo), SUM(contagio) FROM carteira").fetchone()
        if not tot[0]:
            estat_set("carteira_resumo", None); return
        y_n, y_ins, y_rj = tot[0], tot[1] or 0, tot[2] or 0
        taxas = {}
        for d in DIMS:  # d vem da lista fixa DIMS
            rows = c.execute(f"SELECT {d} AS cat, COUNT(*) n, SUM(em_insolvencia) ins, SUM(em_rj) rj FROM carteira GROUP BY {d}").fetchall()
            est = 0.0; p = y_rj / y_n
            for r in rows:
                e1 = r["n"] * p; e0 = r["n"] - e1
                if e1 > 0 and e0 > 0: est += (r["rj"] - e1) ** 2 / e1 + ((r["n"] - r["rj"]) - e0) ** 2 / e0
            pv = p_qui2(est, len(rows) - 1)
            linhas = []
            for r in rows:
                ic = AA.wilson(r["rj"] or 0, r["n"])
                linhas.append({"categoria": r["cat"] or "NI", "cnpjs": r["n"], "insolvencia": r["ins"] or 0, "rj": r["rj"] or 0,
                               "taxa_rj": round((r["rj"] or 0) / r["n"] * 100, 2), "ic95_inf": ic[0], "ic95_sup": ic[1]})
            taxas[d] = {"qui2_p": round(pv, 6) if pv is not None else None, "linhas": sorted(linhas, key=lambda x: -x["rj"])}
        foco = CFG.get("segmento_foco", "MD")
        f = c.execute("SELECT COUNT(*), SUM(em_rj) FROM carteira WHERE seg2=?", (foco,)).fetchone()
        foco_setor = [dict(r) for r in c.execute("SELECT setor, COUNT(*) cnpjs, SUM(em_rj) rj, ROUND(100.0*SUM(em_rj)/COUNT(*),2) taxa_rj FROM carteira WHERE seg2=? GROUP BY setor ORDER BY taxa_rj DESC", (foco,))]
        des = {r[0]: r[1] for r in c.execute("SELECT em_rj, AVG(qualidade<>'OK' AND qualidade<>'Faturamento zero/ausente')*100 FROM carteira GROUP BY em_rj")}
        multi = c.execute("SELECT COUNT(*) FROM (SELECT raiz_grupo FROM carteira WHERE em_rj=1 GROUP BY raiz_grupo HAVING COUNT(*)>1)").fetchone()[0]
        afet = c.execute("SELECT COUNT(DISTINCT raiz_grupo) FROM carteira WHERE em_insolvencia=1").fetchone()[0]
        grupos = [dict(r) for r in c.execute("""SELECT raiz_grupo, MIN(razao) exemplo, SUM(em_insolvencia) cnpjs_insolv, COUNT(*) cnpjs_grupo,
               SUM(contagio) cnpjs_sem_restricao FROM carteira GROUP BY raiz_grupo HAVING SUM(em_insolvencia)>0 ORDER BY cnpjs_insolv DESC, cnpjs_sem_restricao DESC LIMIT 50""")]
        com_proc = [dict(r) for r in c.execute("""SELECT k.razao, k.unidade, k.segmento, pa.papel, p.processo, p.tribunal, p.tipo, p.ajuizamento, p.passivo
               FROM carteira k JOIN partes pa ON pa.raiz=k.raiz JOIN processos p ON p.processo=pa.processo
               WHERE pa.papel IN ('devedora','citada') GROUP BY k.cnpj, p.processo ORDER BY p.ultima_pub DESC LIMIT 300""")]
        pads = c.execute("""SELECT seg2, setor, regiao, faixa_fat, (qualidade IN ('Faturamento > 2 anos','Data 1899 (sentinela)')) desat,
               COUNT(*) n, SUM(em_rj) rj FROM carteira GROUP BY 1,2,3,4,5""").fetchall()
    resumo = {"cnpjs": y_n, "grupos": tot[4], "insolvencia": y_ins, "rj": y_rj, "falencia": tot[3] or 0, "taxa_insolv": round(y_ins / y_n * 100, 2),
              "taxa_rj": round(y_rj / y_n * 100, 2), "grupos_afetados": afet, "grupos_multi_rj": multi, "contagio": tot[5] or 0,
              "foco": foco, "foco_cnpjs": f[0], "foco_rj": f[1] or 0, "foco_taxa_rj": round((f[1] or 0) / f[0] * 100, 2) if f[0] else None,
              "foco_part_rj": round((f[1] or 0) / y_rj * 100, 1) if y_rj else None,
              "desatual_rj": round(des.get(1, 0) or 0, 1), "desatual_demais": round(des.get(0, 0) or 0, 1), "com_processo": len({x["razao"] for x in com_proc})}
    estat_set("carteira_resumo", resumo); estat_set("carteira_taxas", taxas); estat_set("carteira_foco_setor", foco_setor)
    estat_set("carteira_grupos", grupos); estat_set("carteira_processos", com_proc)
    if y_rj >= 15:
        _logit([dict(p) for p in pads])


def _logit(pads):
    ref = {}
    for v in ("seg2", "setor", "regiao", "faixa_fat"):
        cont = {}
        for p in pads: cont[p[v]] = cont.get(p[v], 0) + p["n"]
        cats = [k for k, n in cont.items() if n >= 200]
        ref[v] = sorted(cats, key=lambda k: -cont[k])[1:]
    nomes = ["constante"] + [f"{v}={k}" for v in ref for k in ref[v]] + ["faturamento desatualizado"]
    X, Y, N = [], [], []
    for p in pads:
        X.append([1.0] + [float(p[v] == k) for v in ref for k in ref[v]] + [float(p["desat"])]); Y.append(p["rj"] or 0); N.append(p["n"])
    try:
        b, ep, _ = _irls(X, Y, N, "binomial")
    except ValueError:
        return
    tab = [{"variavel": n, "coef": round(bi, 4), "odds_ratio": round(math.exp(bi), 3), "p_valor": round(_p_normal(bi, e), 4) if e else None}
           for n, bi, e in zip(nomes, b, ep)]
    pr = [1 / (1 + math.exp(-sum(a * c for a, c in zip(x, b)))) for x in X]
    ordem = sorted(zip(pr, Y, N)); pos = sum(Y); neg = sum(N) - pos; acum_neg = 0; auc = 0.0; i = 0
    while i < len(ordem):
        j = i; p_, n_ = 0, 0
        while j < len(ordem) and ordem[j][0] == ordem[i][0]:
            p_ += ordem[j][1]; n_ += ordem[j][2] - ordem[j][1]; j += 1
        auc += p_ * (acum_neg + n_ / 2); acum_neg += n_; i = j
    estat_set("carteira_logit", {"tabela": sorted(tab, key=lambda r: (r["p_valor"] is None, r["p_valor"])),
                                 "auc": round(auc / (pos * neg), 3) if pos and neg else None, "padroes": len(pads)})
    with ana() as c:
        rows = c.execute("""SELECT cnpj, razao, raiz_grupo, unidade, segmento, seg2, setor, regiao, faixa_fat, uf, qualidade, contagio,
               (qualidade IN ('Faturamento > 2 anos','Data 1899 (sentinela)')) desat FROM carteira WHERE em_insolvencia=0""").fetchall()
    out = []
    for r in rows:
        x = [1.0] + [float(r[v] == k) for v in ref for k in ref[v]] + [float(r["desat"])]
        p = 1 / (1 + math.exp(-sum(a * c for a, c in zip(x, b))))
        out.append((p + 0.02 * r["contagio"], r, p))
    out.sort(key=lambda t: -t[0])
    estat_set("carteira_vigilancia", [{"cnpj": r["cnpj"], "razao": r["razao"], "grupo": r["raiz_grupo"], "unidade": r["unidade"], "segmento": r["segmento"],
                                       "setor": r["setor"], "uf": r["uf"], "qualidade": r["qualidade"], "contagio_grupo": bool(r["contagio"]),
                                       "propensao_%": round(p * 100, 2)} for _, r, p in out[:200]])


def coleta_status():
    """Transparência para o portal: última execução de cada etapa e volume de cada base."""
    from .coleta.fontes import DESCRICAO
    with ana() as c:
        ult = {r["etapa"]: dict(r) for r in c.execute("""SELECT etapa, MAX(fim) fim, situacao, linhas FROM coleta_execucoes
                                                         WHERE fim IS NOT NULL GROUP BY etapa""")}
        vol = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
               ("datajud_mensal", "datajud_processos", "djen_publicacoes", "djen_editais", "credores", "cvm_insolvencia", "macro_mensal", "curva", "processos", "partes", "grupos")}
    estat_set("coleta", {"etapas": [{"etapa": k, "fonte": v[0], "descricao": v[1], "ultima": (ult.get(k) or {}).get("fim"),
                                     "situacao": (ult.get(k) or {}).get("situacao"), "linhas": (ult.get(k) or {}).get("linhas")} for k, v in DESCRICAO.items()],
                         "volumes": vol})


def montar():
    for f in (nacional, macro, avancado, processos, credores, concentracao_credores, carteira, coleta_status):
        try:
            f()
        except Exception:
            log.exception("Falha em %s", f.__name__)
    estat_set("atualizado_em", dt.datetime.now().strftime("%d/%m/%Y %H:%M"))
