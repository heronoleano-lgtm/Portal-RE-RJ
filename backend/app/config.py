"""Configuração e segredos. Nenhum segredo fica no código-fonte.
- config/config.json      : parâmetros não sensíveis (gerado na 1ª execução)
- dados/.segredos/*.key   : chaves geradas localmente (nunca servidas)
- variáveis de ambiente   : MOTOR_PROXY, MOTOR_PROXY_USER/PASS, MOTOR_CA_BUNDLE, MOTOR_HTTPS, MOTOR_EDICAO,
                            MOTOR_HOST, MOTOR_PORTA, MOTOR_DADOS_DIR
"""
import json, os, secrets, stat

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR_CONFIG = os.path.join(RAIZ, "config")
DIR_DADOS = os.environ.get("MOTOR_DADOS_DIR") or os.path.join(RAIZ, "dados")
DIR_SEGREDOS = os.path.join(DIR_DADOS, ".segredos")
DIR_LOGS = os.path.join(DIR_DADOS, "logs")
DIR_FRONT = os.path.join(RAIZ, "frontend")
DB_SISTEMA = os.path.join(DIR_DADOS, "sistema.db")      # usuários, sessões, auditoria, assinaturas, SAC, interessados
DB_ANALITICO = os.path.join(DIR_DADOS, "analitico.db")  # dados coletados, cruzamentos e estatísticas

for d in (DIR_DADOS, DIR_SEGREDOS, DIR_LOGS):
    os.makedirs(d, exist_ok=True)

PADRAO = {
    "servidor": {"host": "127.0.0.1", "porta": 8750, "https_atras_de_proxy_reverso": False,
                 "sessao_horas": 8, "sessao_ociosa_min": 30, "max_corpo_kb": 256},
    "rede": {"proxy": "", "usar_proxy_do_sistema": True, "ca_bundle": "", "timeout_seg": 60, "tentativas": 3},
    "datajud": {"chave_publica": "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw==",
                "wiki_chave": "https://datajud-wiki.cnj.jus.br/api-publica/acesso/",
                "classes": {"RJ": 129, "RE": 128, "FAL": 108},
                "tribunais": ["tjsp", "tjrj", "tjmg", "tjpr", "tjsc", "tjrs", "tjgo", "tjmt", "tjms", "tjba", "tjpe", "tjce", "tjdft", "tjes",
                              "tjpa", "tjam", "tjma", "tjpb", "tjrn", "tjal", "tjse", "tjpi", "tjto", "tjro", "tjac", "tjap", "tjrr"],
                "ano_inicial": 2016,
                "enriquecer_max": 400, "reconsultar_dias": 30},
    "djen": {"dias": 30, "dias_credores": 90},
    "bcb_series": {"selic_meta": 432, "ipca_mensal": 433, "ibc_br_dessaz": 24364, "cambio_usd": 1, "juros_pj_livres": 20715,
                   "spread_pj_livres": 20785, "inadimpl_pj_total": 21083, "concessoes_pj_livres": 20631, "saldo_credito_pj": 20541,
                   "desemprego_pnad": 24369},
    "tesouro_csv": "https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv",
    "observatorio_repos": ["abjur/obsFase2"],
    "segmento_foco": "MD",
    "portal": {"exigir_cadastro": True, "validade_cadastro_dias": 180, "retencao_dias": 730,
               "controlador": "", "email_privacidade": ""},
    "edicao": "interna",
    "_edicao_obs": "interna = uso corporativo (carteira e PSI habilitados). publica = portal web: SOMENTE dados públicos.",
}


def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v
    return a


def carregar():
    p = os.path.join(DIR_CONFIG, "config.json")
    cfg = json.loads(json.dumps(PADRAO))
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            _merge(cfg, json.load(f))
    else:
        os.makedirs(DIR_CONFIG, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(PADRAO, f, ensure_ascii=False, indent=1)
    if os.environ.get("MOTOR_PROXY"):
        cfg["rede"]["proxy"] = os.environ["MOTOR_PROXY"]
    if os.environ.get("MOTOR_CA_BUNDLE"):
        cfg["rede"]["ca_bundle"] = os.environ["MOTOR_CA_BUNDLE"]
    if os.environ.get("MOTOR_EDICAO") in ("interna", "publica"):
        cfg["edicao"] = os.environ["MOTOR_EDICAO"]
    if os.environ.get("MOTOR_HOST"):
        cfg["servidor"]["host"] = os.environ["MOTOR_HOST"]
    if os.environ.get("MOTOR_PORTA", "").isdigit():
        cfg["servidor"]["porta"] = int(os.environ["MOTOR_PORTA"])
    if os.environ.get("MOTOR_HTTPS") == "1":
        cfg["servidor"]["https_atras_de_proxy_reverso"] = True
    return cfg


def salvar_parcial(chave, valor):
    """Grava apenas parâmetros NÃO sensíveis no config.json."""
    p = os.path.join(DIR_CONFIG, "config.json")
    c = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            c = json.load(f)
    c[chave] = valor
    with open(p, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)


def segredo(nome, n=32):
    p = os.path.join(DIR_SEGREDOS, nome + ".key")
    if not os.path.exists(p):
        with open(p, "w") as f:
            f.write(secrets.token_hex(n))
        try:
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    with open(p) as f:
        return f.read().strip()


CFG = carregar()
PUBLICA = CFG.get("edicao") == "publica"
RECURSOS_RESTRITOS = ("carteira", "psi")  # nunca disponíveis na edição pública
