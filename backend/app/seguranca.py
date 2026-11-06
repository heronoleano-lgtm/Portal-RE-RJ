"""Primitivas de segurança (somente biblioteca padrão).
- Senhas: PBKDF2-HMAC-SHA256, 600.000 iterações, sal de 16 bytes, comparação em tempo constante
- 2FA: TOTP (RFC 6238) – obrigatório para o mantenedor
- Tokens (sessão e cadastro de interessados): 256 bits; no banco fica só o SHA-256
- Limitação de tentativas por IP e por conta; política de senha forte
"""
import base64, hashlib, hmac, os, re, secrets, struct, time, threading


class ErroUsuario(Exception):
    """Mensagem segura para exibir ao usuário. Qualquer outra exceção vira mensagem genérica + código de incidente."""


ITER = 600_000


def hash_senha(senha):
    sal = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, ITER)
    return f"pbkdf2_sha256${ITER}${base64.b64encode(sal).decode()}${base64.b64encode(h).decode()}"


def confere_senha(senha, armazenado):
    try:
        _, it, sal, h = armazenado.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", senha.encode(), base64.b64decode(sal), int(it))
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


_HASH_FALSO = None


def atraso_uniforme(senha):
    """PBKDF2 mesmo quando o usuário não existe (evita descobrir logins pelo tempo de resposta)."""
    global _HASH_FALSO
    if _HASH_FALSO is None:
        _HASH_FALSO = hash_senha(secrets.token_hex(8))
    confere_senha(senha, _HASH_FALSO)


def politica_senha(s):
    if len(s) < 12:
        return "A senha deve ter ao menos 12 caracteres."
    if not (re.search(r"[A-Z]", s) and re.search(r"[a-z]", s) and re.search(r"\d", s) and re.search(r"[^A-Za-z0-9]", s)):
        return "Use letras maiúsculas, minúsculas, números e símbolos."
    return None


def novo_segredo_totp():
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _hotp(seg, cont):
    k = base64.b32decode(seg + "=" * (-len(seg) % 8))
    d = hmac.new(k, struct.pack(">Q", cont), hashlib.sha1).digest()
    o = d[-1] & 15
    return f"{(struct.unpack('>I', d[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def confere_totp(seg, codigo, janela=1):
    if not seg or not re.fullmatch(r"\d{6}", codigo or ""):
        return False
    t = int(time.time() // 30)
    return any(hmac.compare_digest(_hotp(seg, t + d), codigo) for d in range(-janela, janela + 1))


def uri_totp(seg, conta, emissor="ObservatorioRJ"):
    return f"otpauth://totp/{emissor}:{conta}?secret={seg}&issuer={emissor}&digits=6&period=30"


def novo_token():
    return secrets.token_urlsafe(32)


def h256(t):
    return hashlib.sha256(t.encode()).hexdigest()


class Limitador:
    def __init__(self, maximo, janela_seg):
        self.max, self.jan, self.reg, self.lock = maximo, janela_seg, {}, threading.Lock()

    def permitido(self, chave):
        agora = time.time()
        with self.lock:
            v = [t for t in self.reg.get(chave, []) if agora - t < self.jan]
            self.reg[chave] = v
            return len(v) < self.max

    def registra(self, chave):
        with self.lock:
            self.reg.setdefault(chave, []).append(time.time())

    def limpa(self, chave):
        with self.lock:
            self.reg.pop(chave, None)


LOGIN_IP = Limitador(10, 15 * 60)
LOGIN_CONTA = Limitador(6, 15 * 60)
REQ_IP = Limitador(300, 60)
SAC_IP = Limitador(5, 60 * 60)
CADASTRO_IP = Limitador(5, 60 * 60)

RX_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")
RX_LOGIN = re.compile(r"^[a-z0-9._\-]{3,40}$")


def texto(v, maximo=2000, obrig=True):
    if v is None or (isinstance(v, str) and not v.strip()):
        if obrig:
            raise ErroUsuario("Campo obrigatório não informado.")
        return ""
    if not isinstance(v, str):
        raise ErroUsuario("Formato inválido.")
    v = v.strip()
    if len(v) > maximo:
        raise ErroUsuario("Texto acima do limite permitido.")
    return "".join(c for c in v if c == "\n" or c == "\t" or ord(c) >= 32)


def mascara_cnpj(c):
    c = re.sub(r"\D", "", c or "")
    return f"{c[:2]}.{c[2:5]}.***/****-{c[-2:]}" if len(c) == 14 else "***"


def csv_seguro(v):
    """Neutraliza injeção de fórmulas ao exportar CSV para planilhas."""
    return "'" + v if isinstance(v, str) and v[:1] in "=+-@\t\r" else v
