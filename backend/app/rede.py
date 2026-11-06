"""Cliente HTTP sem dependências externas (urllib) – funciona dentro e fora da rede corporativa.
Ordem de resolução do proxy: MOTOR_PROXY/config → proxy do sistema → PAC corporativo → conexão direta.
A rota que funcionar é memorizada (sem senha). Inspeção TLS: certificado raiz em rede.ca_bundle/MOTOR_CA_BUNDLE.
A verificação de certificado NUNCA é desligada."""
import json, os, re, ssl, socket, time, logging, urllib.request, urllib.parse, urllib.error

from .config import CFG, DIR_SEGREDOS

log = logging.getLogger("motor.rede")
UA = "ObservatorioRJ/9.0 (+pesquisa estatistica)"
_ARQ_OK = os.path.join(DIR_SEGREDOS, "proxy_ok.txt")
_cache = {"proxy": None, "decidido": False}


def _ctx():
    ctx = ssl.create_default_context()
    ca = CFG["rede"].get("ca_bundle")
    if ca and os.path.exists(ca):
        ctx.load_verify_locations(ca)
    try:
        ctx.load_default_certs()
    except Exception:
        pass
    return ctx


def _proxies_sistema():
    out = []
    try:
        p = urllib.request.getproxies()
        for k in ("https", "http"):
            if p.get(k):
                out.append(p[k])
    except Exception:
        pass
    return out


def _proxies_pac():
    url = None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            url = winreg.QueryValueEx(k, "AutoConfigURL")[0]
    except Exception:
        url = os.environ.get("MOTOR_PAC_URL")
    if not url:
        return []
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=_ctx()))
        txt = op.open(url, timeout=15).read().decode("utf-8", "ignore")
        vistos = []
        for a in re.findall(r"PROXY\s+([A-Za-z0-9\.\-]+:\d{2,5})", txt):
            if a not in vistos:
                vistos.append(a)
        return ["http://" + a for a in vistos[:6]]
    except Exception as e:
        log.info("PAC não lido: %s", type(e).__name__)
        return []


def _com_credencial(px):
    u, s = os.environ.get("MOTOR_PROXY_USER"), os.environ.get("MOTOR_PROXY_PASS")
    if px and u and s and "@" not in px:
        pr = urllib.parse.urlsplit(px)
        return f"{pr.scheme}://{urllib.parse.quote(u)}:{urllib.parse.quote(s)}@{pr.netloc}"
    return px


def _opener(proxy):
    hs = [urllib.request.HTTPSHandler(context=_ctx())]
    if proxy:
        proxy = _com_credencial(proxy)
        hs.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        hs.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*hs)


def _mascara(px):
    return re.sub(r"//[^@/]+@", "//***@", px or "direto")


def candidatos():
    c = []
    if CFG["rede"].get("proxy"):
        c.append(CFG["rede"]["proxy"])
    if os.path.exists(_ARQ_OK):
        c.append(open(_ARQ_OK).read().strip() or None)
    if CFG["rede"].get("usar_proxy_do_sistema", True):
        c += _proxies_sistema() + _proxies_pac()
    c.append(None)
    out = []
    for x in c:
        if x not in out:
            out.append(x)
    return out


def _explica(e):
    s = str(getattr(e, "reason", "") or e)
    if "10061" in s or "Connection refused" in s:
        return "conexão recusada (firewall exige proxy ou proxy indicado não está ativo)"
    if "CERTIFICATE_VERIFY_FAILED" in s:
        return "certificado não confiável (inspeção TLS corporativa – configure o certificado raiz em rede.ca_bundle)"
    if "407" in s:
        return "proxy exige autenticação (defina MOTOR_PROXY_USER e MOTOR_PROXY_PASS)"
    if "timed out" in s or isinstance(e, socket.timeout):
        return "tempo esgotado"
    if "11004" in s or "11001" in s or "getaddrinfo" in s or "Temporary failure in name resolution" in s or "Name or service not known" in s:
        return "nome não resolvido (sem DNS externo – rede exige proxy)"
    return s[:90] or type(e).__name__


def _teste(proxy, url="https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"):
    try:
        r = _opener(proxy).open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15)
        return r.status, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}" + (" – bloqueio do proxy/filtro de conteúdo" if e.code == 403 else " – proxy exige autenticação" if e.code == 407 else "")
    except Exception as e:
        return None, _explica(e)


def decidir_proxy(forcar=False):
    if _cache["decidido"] and not forcar:
        return _cache["proxy"]
    for px in candidatos():
        st, _ = _teste(px)
        if st:
            _cache.update(proxy=px, decidido=True)
            if px:
                with open(_ARQ_OK, "w") as f:
                    f.write(re.sub(r"//[^@/]+@", "//", px))
            log.info("Rota de rede escolhida: %s", _mascara(px))
            return px
    _cache.update(proxy=None, decidido=True)
    return None


def requisitar(url, metodo="GET", corpo=None, cabecalhos=None, params=None, timeout=None, tentativas=None):
    """Retorna (status, bytes). Em falha definitiva retorna (None, None) e registra só no log do servidor."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(cabecalhos or {})
    dados = None
    if corpo is not None:
        dados = json.dumps(corpo).encode() if not isinstance(corpo, (bytes, str)) else (corpo.encode() if isinstance(corpo, str) else corpo)
        h.setdefault("Content-Type", "application/json")
    tent = tentativas or CFG["rede"]["tentativas"]
    op = _opener(decidir_proxy())
    for i in range(tent):
        try:
            r = op.open(urllib.request.Request(url, data=dados, headers=h, method=metodo), timeout=timeout or CFG["rede"]["timeout_seg"])
            return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and i < tent - 1:
                time.sleep(3 * (i + 1)); continue
            return e.code, e.read() if hasattr(e, "read") else None
        except Exception as e:
            log.warning("Falha de rede (%s/%s) %s: %s", i + 1, tent, url.split("?")[0][:80], _explica(e))
            time.sleep(2 * (i + 1))
    return None, None


def requisitar_json(url, **kw):
    st, b = requisitar(url, **kw)
    if st and 200 <= st < 300 and b:
        try:
            return json.loads(b.decode("utf-8", "ignore"))
        except ValueError:
            return None
    return None


ALVOS = [("DataJud (CNJ)", "DATAJUD"),
         ("DJEN (CNJ)", "https://comunicaapi.pje.jus.br/api/v1/comunicacao?itensPorPagina=1"),
         ("CVM", "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/"),
         ("BCB SGS", "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"),
         ("BCB Focus", "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"),
         ("Tesouro Transparente", "https://www.tesourotransparente.gov.br/ckan/"),
         ("GitHub (Observatório da Insolvência)", "https://codeload.github.com/abjur/obsFase2"),
         ("Receita Federal", "https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/")]


def diagnostico():
    """Relatório de rede para o mantenedor. Senhas são mascaradas."""
    linhas = {"rotas": [], "fontes": []}
    for px in candidatos():
        st, err = _teste(px)
        linhas["rotas"].append({"rota": _mascara(px), "status": st, "resultado": "OK" if st else err})
    escolhido = decidir_proxy(forcar=True)
    linhas["rota_escolhida"] = _mascara(escolhido)
    op = _opener(escolhido)
    for nome, url in ALVOS:
        try:
            if url == "DATAJUD":
                rq = urllib.request.Request("https://api-publica.datajud.cnj.jus.br/api_publica_tjpr/_search", data=b'{"size":0}', method="POST",
                                            headers={"User-Agent": UA, "Content-Type": "application/json", "Authorization": "APIKey " + CFG["datajud"]["chave_publica"]})
            else:
                rq = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
            r = op.open(rq, timeout=25)
            linhas["fontes"].append({"fonte": nome, "status": r.status, "resultado": "OK"})
        except urllib.error.HTTPError as e:
            msg = {401: "chave recusada (o motor renova a chave automaticamente na coleta)", 403: "bloqueado (403) – provável filtro do proxy corporativo",
                   407: "proxy exige autenticação (MOTOR_PROXY_USER / MOTOR_PROXY_PASS)", 404: "endereço não encontrado"}.get(e.code, "erro no servidor" if e.code >= 500 else f"HTTP {e.code}")
            linhas["fontes"].append({"fonte": nome, "status": e.code, "resultado": msg})
        except Exception as e:
            linhas["fontes"].append({"fonte": nome, "status": None, "resultado": _explica(e)})
    return linhas
