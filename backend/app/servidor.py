"""Back-end HTTP (biblioteca padrão). Front-end e back-end separados: o navegador recebe arquivos estáticos e
conversa com /api/v1/* em JSON. Rotas do mantenedor respondem 404 para os demais perfis.
Produção: publicar atrás de proxy reverso com TLS (deploy/: Caddy)."""
import gzip, hashlib, ipaddress, http.server, json, logging, logging.handlers, mimetypes, os, re, secrets, socketserver, time, traceback, urllib.parse
from http import cookies

from .config import CFG, DIR_FRONT, DIR_LOGS, RAIZ, PUBLICA
from . import db, seguranca as S
from .seguranca import ErroUsuario

LOG = logging.getLogger("motor")
COOKIE = "mrj_sid"          # sessão da área restrita
COOKIE_VIS = "mrj_vis"      # cadastro de interessado no portal
ROTAS = []  # (metodo, regex, funcao, nivel)  nivel: publico | usuario | mantenedor


def rota(metodo, padrao, nivel="usuario"):
    def deco(fn):
        ROTAS.append((metodo, re.compile("^" + padrao + "$"), fn, nivel)); return fn
    return deco


ESTATICOS, PROTEGIDOS, GZ = {}, {}, {}
VERSAO_ATIVOS = ""


def carregar_estaticos():
    global VERSAO_ATIVOS
    for base, prefixo in (("static", "/static/"), ("vendor", "/vendor/")):
        d = os.path.join(DIR_FRONT, base)
        for nome in os.listdir(d):
            p = os.path.join(d, nome)
            if os.path.isfile(p) and not nome.startswith("."):
                alvo = PROTEGIDOS if nome.startswith("mnt") else ESTATICOS
                alvo[prefixo + nome] = open(p, "rb").read()
    VERSAO_ATIVOS = hashlib.sha256(b"".join(ESTATICOS[k] for k in sorted(ESTATICOS))).hexdigest()[:10]
    ESTATICOS["/"] = open(os.path.join(DIR_FRONT, "index.html"), "rb").read().replace(b"__V__", VERSAO_ATIVOS.encode())
    for k, v in list(ESTATICOS.items()) + list(PROTEGIDOS.items()):
        if len(v) > 1024:
            GZ[k] = gzip.compress(v, 9)


CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def ip_cliente(h):
    """X-Real-IP só é aceito vindo de proxy reverso confiável."""
    orig = h.client_address[0]
    if CFG["servidor"]["https_atras_de_proxy_reverso"]:
        try:
            ipo = ipaddress.ip_address(orig)
            confiavel = ipo.is_loopback or orig in {x.strip() for x in os.environ.get("MOTOR_PROXIES_CONFIAVEIS", "").split(",") if x.strip()} \
                or (ipo.is_private and os.environ.get("MOTOR_CONFIAR_PROXY_PRIVADO") == "1")
        except ValueError:
            confiavel = False
        if confiavel:
            try:
                return str(ipaddress.ip_address((h.headers.get("X-Real-IP") or "").strip()))
            except ValueError:
                pass
    return orig


class Ctx:
    def __init__(self, h, usuario=None, sessao=None, corpo=None, params=None, visitante=None):
        self.h, self.usuario, self.sessao, self.corpo, self.params, self.visitante = h, usuario, sessao, corpo or {}, params or {}, visitante

    @property
    def ip(self):
        return ip_cliente(self.h)

    @property
    def liberado(self):
        """Conteúdo completo do portal: cadastro não exigido, interessado cadastrado ou usuário da área restrita."""
        return (not CFG["portal"].get("exigir_cadastro", True)) or bool(self.usuario) or bool(self.visitante)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "web"
    sys_version = ""
    timeout = 30

    def version_string(self):
        return "web"

    def log_message(self, fmt, *a):
        LOG.debug("%s %s", self.client_address[0], fmt % a)

    def _cab(self, status, tipo, tam, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", tipo); self.send_header("Content-Length", str(tam))
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer"); self.send_header("Content-Security-Policy", CSP)
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin"); self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if CFG["servidor"]["https_atras_de_proxy_reverso"]:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        for k, v in (extra or {}).items():
            if isinstance(v, list):
                for x in v:
                    self.send_header(k, x)
            else:
                self.send_header(k, v)
        self.end_headers()

    def _aceita_gzip(self):
        return "gzip" in (self.headers.get("Accept-Encoding") or "")

    def json(self, obj, status=200, extra=None, cache=None):
        """cache: None (no-store) · 'publico' (CDN/navegador, 5 min) · 'privado' (só navegador; conteúdo varia por cadastro)."""
        b = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":")).encode()
        e = {"Cache-Control": {"publico": "public, max-age=300", "privado": "private, no-cache"}.get(cache, "no-store")}
        if cache:
            etag = '"' + hashlib.sha256(b).hexdigest()[:20] + '"'; e["ETag"] = etag
            if cache == "privado":
                e["Vary"] = "Cookie"
            if self.headers.get("If-None-Match") == etag:
                self._cab(304, "application/json; charset=utf-8", 0, e); return
        e.update(extra or {})
        if len(b) > 1024 and self._aceita_gzip():
            b = gzip.compress(b, 6); e["Content-Encoding"] = "gzip"; e["Vary"] = (e.get("Vary", "") + ", Accept-Encoding").strip(", ")
        self._cab(status, "application/json; charset=utf-8", len(b), e); self.wfile.write(b)

    def nao_encontrado(self):
        self.json({"erro": "Recurso não encontrado."}, 404)

    def _cookie(self, nome):
        ck = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return ck[nome].value if nome in ck else None

    def _sessao(self):
        tok = self._cookie(COOKIE)
        if not tok:
            return None, None
        th = S.h256(tok); agora = time.time()
        with db.sis() as c:
            s = c.execute("SELECT * FROM sessoes WHERE token_h=?", (th,)).fetchone()
            if not s:
                return None, None
            if s["expira"] < agora or agora - s["visto"] > CFG["servidor"]["sessao_ociosa_min"] * 60:
                c.execute("DELETE FROM sessoes WHERE token_h=?", (th,)); return None, None
            u = c.execute("SELECT * FROM usuarios WHERE id=? AND ativo=1", (s["usuario_id"],)).fetchone()
            if not u:
                return None, None
            c.execute("UPDATE sessoes SET visto=? WHERE token_h=?", (agora, th))
        return dict(u), dict(s)

    def _visitante(self):
        tok = self._cookie(COOKIE_VIS)
        if not tok:
            return None
        agora = time.time()
        with db.sis() as c:
            v = c.execute("SELECT id, nome, ultimo_acesso FROM interessados WHERE token_h=? AND expira>?", (S.h256(tok), agora)).fetchone()
            if v and agora - (v["ultimo_acesso"] or 0) > 3600:
                c.execute("UPDATE interessados SET ultimo_acesso=?, acessos=acessos+1 WHERE id=?", (agora, v["id"]))
        return dict(v) if v else None

    def _mesma_origem(self):
        o = self.headers.get("Origin") or self.headers.get("Referer") or ""
        return True if not o else urllib.parse.urlsplit(o).netloc == self.headers.get("Host", "")

    def _tratar(self, metodo):
        ip = ip_cliente(self)
        if not S.REQ_IP.permitido(ip):
            return self.json({"erro": "Muitas requisições. Aguarde um instante."}, 429)
        S.REQ_IP.registra(ip)
        url = urllib.parse.urlsplit(self.path); caminho = url.path
        if caminho.startswith("/api/v1/"):
            caminho = "/api/" + caminho[8:]
        try:
            if metodo == "GET" and not caminho.startswith("/api/"):
                return self._estatico(caminho)
            usuario, sessao = self._sessao()
            for m, rx, fn, nivel in ROTAS:
                mt = rx.match(caminho)
                if m != metodo or not mt:
                    continue
                if nivel != "publico" and not usuario:
                    return self.json({"erro": "Sessão expirada. Entre novamente."}, 401)
                if nivel == "mantenedor" and usuario["papel"] != "mantenedor":
                    db.auditar("sondagem_area_restrita", usuario, ip, {"rota": caminho})
                    return self.nao_encontrado()
                if metodo != "GET":
                    if not self._mesma_origem():
                        return self.nao_encontrado()
                    if usuario and not secrets.compare_digest(self.headers.get("X-CSRF", ""), sessao["csrf"]):
                        return self.json({"erro": "Sessão inválida. Recarregue a página."}, 403)
                corpo = self._corpo(fn)
                vis = self._visitante() if nivel == "publico" else None
                return fn(Ctx(self, usuario, sessao, corpo, dict(urllib.parse.parse_qsl(url.query)), vis), *mt.groups())
            return self.nao_encontrado()
        except ErroUsuario as e:
            return self.json({"erro": str(e)}, 400)
        except Exception:
            cod = secrets.token_hex(4).upper()
            LOG.error("Incidente %s em %s %s\n%s", cod, metodo, caminho, traceback.format_exc())
            return self.json({"erro": "Não foi possível concluir a operação.", "codigo": cod}, 500)

    def _corpo(self, fn):
        n = int(self.headers.get("Content-Length") or 0)
        limite = (40 * 1024 * 1024) if getattr(fn, "upload", False) else CFG["servidor"]["max_corpo_kb"] * 1024
        if n > limite:
            raise ErroUsuario("Conteúdo acima do tamanho permitido.")
        if not n:
            return {}
        bruto = self.rfile.read(n)
        if getattr(fn, "upload", False):
            return {"_bytes": bruto}
        try:
            d = json.loads(bruto)
        except ValueError:
            raise ErroUsuario("Formato de dados inválido.")
        if not isinstance(d, dict):
            raise ErroUsuario("Formato de dados inválido.")
        return d

    def _estatico(self, caminho):
        if caminho in ("/", "/index.html", "/app", "/entrar", "/portal", "/metodologia", "/contato", "/privacidade"):
            caminho = "/"
        b = ESTATICOS.get(caminho)
        if b is None and caminho in PROTEGIDOS:
            u, _ = self._sessao()
            if u and u["papel"] == "mantenedor":
                b = PROTEGIDOS[caminho]; ex = {"Cache-Control": "no-store"}
                if caminho in GZ and self._aceita_gzip():
                    b = GZ[caminho]; ex.update({"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
                self._cab(200, "text/javascript; charset=utf-8", len(b), ex); return self.wfile.write(b)
        if b is None:
            return self.nao_encontrado()
        tipo = "text/html; charset=utf-8" if caminho == "/" else (mimetypes.guess_type(caminho)[0] or "application/octet-stream")
        if tipo.startswith("text/") or tipo.endswith("javascript"):
            tipo = tipo.split(";")[0] + "; charset=utf-8"
        ex = {"Cache-Control": "no-cache" if caminho == "/" else "public, max-age=31536000, immutable"}
        if caminho in GZ and self._aceita_gzip():
            b = GZ[caminho]; ex.update({"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
        self._cab(200, tipo, len(b), ex); self.wfile.write(b)

    def do_GET(self): self._tratar("GET")
    def do_POST(self): self._tratar("POST")
    def do_PUT(self): self._tratar("PUT")
    def do_DELETE(self): self._tratar("DELETE")

    def do_OPTIONS(self):
        self.nao_encontrado()


class Servidor(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def configurar_log():
    h = logging.handlers.RotatingFileHandler(os.path.join(DIR_LOGS, "servidor.log"), maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    raiz = logging.getLogger(); raiz.setLevel(logging.INFO); raiz.addHandler(h)


def verificar_integridade():
    p = os.path.join(RAIZ, "docs", "MANIFESTO.sha256")
    if not os.path.exists(p):
        return {"verificado": False, "alterados": []}
    alt = []
    for linha in open(p, encoding="utf-8"):
        if "  " not in linha:
            continue
        h, arq = linha.strip().split("  ", 1)
        f = os.path.join(RAIZ, arq)
        if not os.path.exists(f) or hashlib.sha256(open(f, "rb").read()).hexdigest() != h:
            alt.append(arq)
    return {"verificado": True, "alterados": alt}


def expurgar_interessados():
    """Retenção: remove cadastros sem acesso há mais de 'retencao_dias'."""
    lim = time.time() - CFG["portal"].get("retencao_dias", 730) * 86400
    with db.sis() as c:
        return c.execute("DELETE FROM interessados WHERE COALESCE(ultimo_acesso, criado) < ?", (lim,)).rowcount


def iniciar():
    configurar_log(); db.inicializar(); carregar_estaticos()
    if PUBLICA:
        n = db.expurgar_restritos()
        if n:
            LOG.warning("Edição pública: %s registros internos removidos na inicialização", n)
    n = expurgar_interessados()
    if n:
        LOG.info("Retenção: %s cadastros de interessados removidos", n)
    from . import rotas  # noqa: F401
    integ = verificar_integridade()
    if integ["alterados"]:
        LOG.warning("Arquivos alterados desde a entrega: %s", integ["alterados"])
    host, porta = CFG["servidor"]["host"], CFG["servidor"]["porta"]
    srv = Servidor((host, porta), Handler)
    print(f"\n  Observatório RJ/RE em execução: http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{porta}\n  (feche esta janela para encerrar)\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
