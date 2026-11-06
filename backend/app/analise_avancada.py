"""Métodos estatísticos (Python puro, sem E/S – camada de domínio, testada em tests/).
Séries temporais: decompor · holt_winters · validacao_cruzada (MASE) · ensemble · pontos_de_quebra (Poisson/BIC)
Concentração: gini · lorenz · hhi        Inferência: wilson · mann_whitney        Sobrevivência: kaplan_meier
"""
import math


def _media(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def _mediana(v):
    v = sorted(x for x in v if x is not None)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


mediana = _mediana


# ---------------------------------------------------------------- decomposição
def decompor(y, periodo=12):
    """Decomposição multiplicativa robusta: tendência MM 2x12, sazonalidade por mediana das razões."""
    n = len(y)
    if n < 2 * periodo + 1:
        return None
    yl = [max(v, 0.5) for v in y]
    meio = periodo // 2
    tend = [None] * n
    for t in range(meio, n - meio):
        janela = yl[t - meio:t + meio + 1]
        tend[t] = (sum(janela[1:-1]) + 0.5 * (janela[0] + janela[-1])) / periodo
    razoes = [[] for _ in range(periodo)]
    for t in range(n):
        if tend[t]:
            razoes[t % periodo].append(yl[t] / tend[t])
    idx = [_mediana(r) or 1.0 for r in razoes]
    f = periodo / sum(idx)
    idx = [i * f for i in idx]

    def _ext(pontos):
        xs = [p[0] for p in pontos]; ys = [p[1] for p in pontos]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        b = sum((a - mx) * (c - my) for a, c in zip(xs, ys)) / max(sum((a - mx) ** 2 for a in xs), 1e-9)
        return lambda t: my + b * (t - mx)
    ini = _ext([(t, tend[t]) for t in range(meio, min(meio + 24, n - meio))])
    fim = _ext([(t, tend[t]) for t in range(max(meio, n - meio - 24), n - meio)])
    for t in range(meio):
        tend[t] = max(ini(t), 0.1)
    for t in range(n - meio, n):
        tend[t] = max(fim(t), 0.1)
    saz = [idx[t % periodo] for t in range(n)]
    res = [yl[t] / (tend[t] * saz[t]) for t in range(n)]
    return {"tendencia": tend, "sazonal": saz, "residuo": res, "indices": idx}


# ---------------------------------------------------------------- Holt-Winters
def _hw_ajuste(z, a, b, g, m):
    n = len(z)
    L = sum(z[:m]) / m
    T = (sum(z[m:2 * m]) - sum(z[:m])) / (m * m) if n >= 2 * m else 0.0
    S = [z[i] - L for i in range(m)]
    sse, aj = 0.0, []
    for t in range(n):
        s = S[t % m]
        prev = L + T + s
        aj.append(prev)
        e = z[t] - prev
        sse += e * e
        Ln = a * (z[t] - s) + (1 - a) * (L + T)
        T = b * (Ln - L) + (1 - b) * T
        S[t % m] = g * (z[t] - Ln) + (1 - g) * s
        L = Ln
    return sse, L, T, S, aj


def _nelder_mead(f, x0, passo=0.1, it=200):
    n = len(x0)
    pts = [list(x0)] + [[x0[j] + (passo if j == i else 0) for j in range(n)] for i in range(n)]
    vals = [f(p) for p in pts]
    for _ in range(it):
        ordem = sorted(range(n + 1), key=lambda i: vals[i])
        pts = [pts[i] for i in ordem]; vals = [vals[i] for i in ordem]
        c = [sum(p[j] for p in pts[:-1]) / n for j in range(n)]
        r = [c[j] + (c[j] - pts[-1][j]) for j in range(n)]; fr = f(r)
        if fr < vals[0]:
            e = [c[j] + 2 * (c[j] - pts[-1][j]) for j in range(n)]; fe = f(e)
            pts[-1], vals[-1] = (e, fe) if fe < fr else (r, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = r, fr
        else:
            k = [c[j] + 0.5 * (pts[-1][j] - c[j]) for j in range(n)]; fk = f(k)
            if fk < vals[-1]:
                pts[-1], vals[-1] = k, fk
            else:
                pts = [pts[0]] + [[pts[0][j] + 0.5 * (p[j] - pts[0][j]) for j in range(n)] for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
        if abs(vals[-1] - vals[0]) < 1e-9:
            break
    return pts[0]


def holt_winters(y, h=12, m=12, nivel_ic=0.80):
    """Holt-Winters aditivo em log; parâmetros por grade + Nelder-Mead; IC com variância de Hyndman et al. (2008)."""
    if len(y) < 2 * m + 6:
        return None
    z = [math.log(max(v, 0.5)) for v in y]
    lim = lambda v: min(max(v, 0.01), 0.99)
    obj = lambda p: _hw_ajuste(z, lim(p[0]), lim(p[1]) * 0.3, lim(p[2]), m)[0]
    melhor = min(([a, b, g] for a in (0.2, 0.5, 0.8) for b in (0.05, 0.2) for g in (0.1, 0.4)), key=obj)
    p = _nelder_mead(obj, melhor)
    a, b, g = lim(p[0]), lim(p[1]) * 0.3, lim(p[2])
    sse, L, T, S, aj = _hw_ajuste(z, a, b, g, m)
    n = len(z)
    sig = math.sqrt(sse / max(n - 3 - m, 1))
    zq = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.96}[nivel_ic]
    prev = []
    for k in range(1, h + 1):
        mu = L + k * T + S[(n + k - 1) % m]
        var = sig ** 2 * (1 + sum((a * (1 + j * b) + (g * (1 - a) if j % m == 0 else 0)) ** 2 for j in range(1, k)))
        sd = math.sqrt(var)
        prev.append({"passo": k, "previsto": math.exp(mu), "inf": math.exp(mu - zq * sd), "sup": math.exp(mu + zq * sd)})
    return {"parametros": {"alfa": round(a, 3), "beta": round(b, 3), "gama": round(g, 3)}, "sigma_log": round(sig, 4),
            "ajustado": [math.exp(v) for v in aj], "previsao": prev}


# ---------------------------------------------------------------- validação e ensemble
def _mase_escala(y, m=12):
    d = [abs(y[t] - y[t - m]) for t in range(m, len(y))]
    return (sum(d) / len(d)) if d else 1.0


def validacao_cruzada(y, previsores, origens=12, h=6, m=12):
    """Rolling-origin. previsores: nome -> função(treino, h) -> lista de h previsões. Retorna MASE e MAPE."""
    n = len(y)
    if n < 3 * m + origens:
        return None
    esc = _mase_escala(y[: n - origens], m) or 1.0
    res = {k: {"ae": [], "ape": []} for k in previsores}
    for o in range(n - origens - h, n - h + 1, max(1, origens // 6)):
        treino, teste = y[:o], y[o:o + h]
        for nome, fn in previsores.items():
            try:
                p = fn(treino, h)
            except Exception:
                p = None
            if not p:
                continue
            for a, b in zip(teste, p):
                res[nome]["ae"].append(abs(a - b))
                if a:
                    res[nome]["ape"].append(abs(a - b) / a)
    out = {}
    for k, v in res.items():
        if v["ae"]:
            out[k] = {"MASE": round(_media(v["ae"]) / esc, 3), "MAPE_%": round(_media(v["ape"]) * 100, 1), "n": len(v["ae"])}
    return out


def ingenuo_sazonal(treino, h, m=12):
    return [treino[len(treino) - m + (k % m)] for k in range(h)]


def ensemble(previsoes, metricas):
    """Pesos ∝ 1/MASE²."""
    pesos = {k: 1 / max(metricas[k]["MASE"], 0.05) ** 2 for k in previsoes if k in metricas}
    tot = sum(pesos.values())
    if not tot:
        return None, {}
    pesos = {k: v / tot for k, v in pesos.items()}
    h = min(len(v) for k, v in previsoes.items() if k in pesos)
    out = [{c: sum(pesos[k] * previsoes[k][i][c] for k in pesos) for c in ("previsto", "inf", "sup")} for i in range(h)]
    return out, {k: round(v, 3) for k, v in pesos.items()}


# ---------------------------------------------------------------- pontos de quebra
def _ll_poisson(seg):
    n = len(seg); s = sum(seg)
    if not n or not s:
        return 0.0
    lam = s / n
    return s * math.log(lam) - n * lam


def pontos_de_quebra(y, min_seg=12, max_quebras=4):
    """Segmentação binária (Poisson) com critério BIC."""
    pen = 2 * math.log(len(y))
    quebras, segs = [], [(0, len(y))]
    while len(quebras) < max_quebras:
        melhor = None
        for (i, j) in segs:
            base = _ll_poisson(y[i:j])
            for k in range(i + min_seg, j - min_seg + 1):
                ganho = _ll_poisson(y[i:k]) + _ll_poisson(y[k:j]) - base
                if ganho * 2 > pen and (melhor is None or ganho > melhor[0]):
                    melhor = (ganho, i, j, k)
        if not melhor:
            break
        _, i, j, k = melhor
        quebras.append(k)
        segs.remove((i, j)); segs += [(i, k), (k, j)]
    quebras.sort()
    lim = [0] + quebras + [len(y)]
    regimes = [{"inicio": lim[r], "fim": lim[r + 1] - 1, "media": round(sum(y[lim[r]:lim[r + 1]]) / (lim[r + 1] - lim[r]), 1)} for r in range(len(lim) - 1)]
    return {"quebras": quebras, "regimes": regimes}


# ---------------------------------------------------------------- concentração e desigualdade
def gini(v):
    v = sorted(x for x in v if x is not None and x >= 0)
    n = len(v); s = sum(v)
    if n < 2 or not s:
        return None
    return round((2 * sum((i + 1) * x for i, x in enumerate(v)) / (n * s)) - (n + 1) / n, 4)


def lorenz(v, pontos=20):
    v = sorted(x for x in v if x is not None and x >= 0)
    n = len(v); s = sum(v)
    if not n or not s:
        return []
    out, acum, k = [{"pop": 0.0, "valor": 0.0}], 0.0, 1
    for i, x in enumerate(v, 1):
        acum += x
        if i >= k * n / pontos or i == n:
            out.append({"pop": round(i / n, 4), "valor": round(acum / s, 4)}); k += 1
    return out


def hhi(valores):
    """HHI 0–10.000 (CADE/DoJ: <1.500 baixo; 1.500–2.500 moderado; >2.500 alto)."""
    tot = sum(v for v in valores if v and v > 0)
    if not tot:
        return None
    return round(sum((v / tot * 100) ** 2 for v in valores if v and v > 0), 1)


def faixa_hhi(h):
    return None if h is None else ("baixa" if h < 1500 else "moderada" if h <= 2500 else "alta")


# ---------------------------------------------------------------- inferência
def wilson(sucessos, n, z=1.96):
    if not n:
        return None, None
    p = sucessos / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(c - m, 0) * 100, 2), round(min(c + m, 1) * 100, 2)


def mann_whitney(a, b):
    """Teste U de Mann-Whitney bilateral (aproximação normal com correção de empates e de continuidade – igual a
    scipy.stats.mannwhitneyu(method='asymptotic')). Retorna (U de a, p-valor)."""
    a = [x for x in a if x is not None]; b = [x for x in b if x is not None]
    n1, n2 = len(a), len(b)
    if n1 < 3 or n2 < 3:
        return None, None
    todos = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    postos, i, empates = [0.0] * len(todos), 0, 0.0
    while i < len(todos):
        j = i
        while j + 1 < len(todos) and todos[j + 1][0] == todos[i][0]:
            j += 1
        for k in range(i, j + 1):
            postos[k] = (i + j) / 2 + 1
        t = j - i + 1; empates += t ** 3 - t; i = j + 1
    r1 = sum(p for p, (_, g) in zip(postos, todos) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2
    n = n1 + n2
    mu = n1 * n2 / 2
    sd = math.sqrt(n1 * n2 / 12 * ((n + 1) - empates / (n * (n - 1))))
    if sd == 0:
        return u1, 1.0
    z = (abs(u1 - mu) - 0.5) / sd
    p = min(1.0, math.erfc(max(z, 0) / math.sqrt(2)))
    return u1, p


# ---------------------------------------------------------------- sobrevivência
def kaplan_meier(duracoes, eventos):
    dados = sorted(zip(duracoes, eventos))
    n = len(dados)
    if n < 10:
        return None
    s, risco, curva, i = 1.0, n, [{"t": 0, "s": 1.0}], 0
    while i < n:
        t = dados[i][0]; d = c = 0
        while i < n and dados[i][0] == t:
            d += dados[i][1]; c += 1 - dados[i][1]; i += 1
        if d:
            s *= 1 - d / risco
            curva.append({"t": t, "s": round(s, 4)})
        risco -= d + c
    med = next((p["t"] for p in curva if p["s"] <= 0.5), None)
    return {"curva": curva, "mediana_dias": med, "n": n, "eventos": sum(e for _, e in dados)}
