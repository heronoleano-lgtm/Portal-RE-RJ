"""Bancos SQLite (sem servidor, sem dependência). Consultas SEMPRE parametrizadas.
sistema.db   -> usuários, sessões, planos, assinaturas, auditoria encadeada, SAC, interessados (cadastro do portal)
analitico.db -> dados coletados (APIs), cruzamentos (processos, partes, grupos), carteira, estatísticas, PSI
"""
import hashlib, json, sqlite3, threading, time
from .config import DB_SISTEMA, DB_ANALITICO

_lock = threading.Lock()

SCHEMA_SISTEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS usuarios(
  id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, nome TEXT NOT NULL, email TEXT NOT NULL,
  senha TEXT NOT NULL, papel TEXT NOT NULL CHECK(papel IN ('mantenedor','gestor','analista','usuario')),
  totp TEXT, ativo INTEGER DEFAULT 1, trocar_senha INTEGER DEFAULT 0, permissoes TEXT DEFAULT '[]',
  falhas INTEGER DEFAULT 0, bloqueado_ate REAL DEFAULT 0, criado REAL, ultimo_acesso REAL);
CREATE TABLE IF NOT EXISTS sessoes(
  token_h TEXT PRIMARY KEY, usuario_id INTEGER NOT NULL, csrf TEXT NOT NULL, criado REAL, visto REAL, expira REAL,
  ip TEXT, agente TEXT, FOREIGN KEY(usuario_id) REFERENCES usuarios(id));
CREATE TABLE IF NOT EXISTS planos(codigo TEXT PRIMARY KEY, nome TEXT, recursos TEXT, ativo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS assinaturas(
  id INTEGER PRIMARY KEY, usuario_id INTEGER NOT NULL, plano TEXT NOT NULL, inicio REAL, fim REAL,
  situacao TEXT DEFAULT 'ativa', obs TEXT, FOREIGN KEY(usuario_id) REFERENCES usuarios(id));
CREATE TABLE IF NOT EXISTS auditoria(
  id INTEGER PRIMARY KEY, quando REAL, usuario_id INTEGER, login TEXT, ip TEXT, acao TEXT, detalhe TEXT,
  hash_anterior TEXT, hash TEXT);
CREATE TABLE IF NOT EXISTS sac_chamados(
  id INTEGER PRIMARY KEY, protocolo TEXT UNIQUE, usuario_id INTEGER, nome TEXT, email TEXT, assunto TEXT,
  categoria TEXT, situacao TEXT DEFAULT 'aberto', criado REAL, atualizado REAL);
CREATE TABLE IF NOT EXISTS sac_mensagens(id INTEGER PRIMARY KEY, chamado_id INTEGER, autor TEXT, interno INTEGER DEFAULT 0, texto TEXT, quando REAL);
CREATE TABLE IF NOT EXISTS recuperacao(usuario_id INTEGER, hash TEXT, usado INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS interessados(
  id INTEGER PRIMARY KEY, nome TEXT NOT NULL, email TEXT NOT NULL, organizacao TEXT, perfil TEXT, interesse TEXT,
  novidades INTEGER DEFAULT 0, consentimento TEXT NOT NULL, criado REAL, ultimo_acesso REAL, acessos INTEGER DEFAULT 0,
  token_h TEXT, expira REAL, ip_h TEXT);
CREATE INDEX IF NOT EXISTS ix_sess_u ON sessoes(usuario_id);
CREATE INDEX IF NOT EXISTS ix_aud_q ON auditoria(quando);
CREATE INDEX IF NOT EXISTS ix_int_tok ON interessados(token_h);
CREATE INDEX IF NOT EXISTS ix_int_email ON interessados(email);
"""

PLANOS = [("basico", "Básico", ["panorama", "macro", "sac"]),
          ("analista", "Analista", ["panorama", "macro", "credores", "sac"]),
          ("corporativo", "Corporativo", ["panorama", "macro", "credores", "carteira", "psi", "sac", "exportar"])]

SCHEMA_ANALITICO = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS coleta_execucoes(id INTEGER PRIMARY KEY, etapa TEXT, inicio REAL, fim REAL, situacao TEXT, linhas INTEGER, nota TEXT);
CREATE TABLE IF NOT EXISTS datajud_mensal(tribunal TEXT, uf TEXT, tipo TEXT, mes TEXT, qtd INTEGER, PRIMARY KEY(tribunal,tipo,mes));
CREATE TABLE IF NOT EXISTS datajud_varas(tribunal TEXT, tipo TEXT, orgao TEXT, qtd INTEGER, PRIMARY KEY(tribunal,tipo,orgao));
CREATE TABLE IF NOT EXISTS datajud_processos(processo TEXT PRIMARY KEY, tribunal TEXT, classe_codigo INTEGER, classe_nome TEXT,
  ajuizamento TEXT, orgao TEXT, mun_ibge TEXT, assuntos TEXT, n_movs INTEGER, dt_deferimento TEXT, dt_concessao TEXT,
  dt_convolacao TEXT, dt_encerramento TEXT, dt_ultima_mov TEXT, encontrado INTEGER, consultado REAL);
CREATE TABLE IF NOT EXISTS djen_publicacoes(id TEXT PRIMARY KEY, termo TEXT, data TEXT, tribunal TEXT, processo TEXT, orgao TEXT,
  tipo_com TEXT, classe TEXT, partes TEXT, cnpjs TEXT, trecho TEXT);
CREATE TABLE IF NOT EXISTS djen_editais(id TEXT PRIMARY KEY, processo TEXT, tribunal TEXT, data TEXT, tipo_edital TEXT, precedencia INTEGER,
  rj_re TEXT, devedora TEXT, cnpjs_devedora TEXT, n_credores INTEGER, valor_extraido REAL, totais TEXT, divergencia TEXT,
  confianca TEXT, lista_em_anexo INTEGER, vigente INTEGER DEFAULT 0, link TEXT);
CREATE TABLE IF NOT EXISTS credores(id INTEGER PRIMARY KEY, edital_id TEXT, processo TEXT, classe TEXT, credor TEXT, doc TEXT,
  tipo_pessoa TEXT, moeda TEXT, valor REAL, banco TEXT, tipo_banco TEXT, match_banco TEXT);
CREATE TABLE IF NOT EXISTS cvm_insolvencia(cnpj TEXT PRIMARY KEY, nome TEXT, setor TEXT, situacao TEXT, desde TEXT, uf TEXT);
CREATE TABLE IF NOT EXISTS macro_mensal(serie TEXT, mes TEXT, valor REAL, PRIMARY KEY(serie,mes));
CREATE TABLE IF NOT EXISTS focus(indicador TEXT, ref TEXT, mediana REAL, data TEXT, PRIMARY KEY(indicador,ref));
CREATE TABLE IF NOT EXISTS curva(momento TEXT, data_base TEXT, curva TEXT, titulo TEXT, vencimento TEXT, prazo REAL, taxa REAL);
CREATE TABLE IF NOT EXISTS curva_mensal(mes TEXT PRIMARY KEY, pre_curto REAL, pre_longo REAL, juro_real_5a REAL, inclinacao REAL);
CREATE TABLE IF NOT EXISTS processos(processo TEXT PRIMARY KEY, tribunal TEXT, uf TEXT, tipo TEXT, classe_nome TEXT, ajuizamento TEXT,
  orgao TEXT, vara_especializada INTEGER, dt_deferimento TEXT, dt_concessao TEXT, dt_convolacao TEXT, dt_encerramento TEXT, dt_ultima_mov TEXT,
  dias_deferimento INTEGER, dias_concessao INTEGER, convolada INTEGER, primeira_pub TEXT, ultima_pub TEXT, n_publicacoes INTEGER,
  devedora TEXT, partes_citadas TEXT, cnpj_principal TEXT, n_devedoras INTEGER, n_raizes INTEGER, grupo INTEGER, passivo REAL, n_credores INTEGER,
  bancos_pct REAL, cvm INTEGER, fontes TEXT);
CREATE TABLE IF NOT EXISTS partes(id INTEGER PRIMARY KEY, processo TEXT, cnpj TEXT, raiz TEXT, nome TEXT, tipo_pessoa TEXT, papel TEXT,
  fonte TEXT, banco TEXT, valor REAL, classe_credito TEXT, cvm_situacao TEXT);
CREATE TABLE IF NOT EXISTS grupos(grupo INTEGER PRIMARY KEY, n_empresas INTEGER, n_processos INTEGER, nomes TEXT, raizes TEXT, ufs TEXT, tribunais TEXT);
CREATE TABLE IF NOT EXISTS carteira(cnpj TEXT PRIMARY KEY, raiz TEXT, raiz_grupo TEXT, razao TEXT, unidade TEXT, carteira TEXT,
  segmento TEXT, seg2 TEXT, cnae TEXT, setor TEXT, faturamento REAL, faixa_fat TEXT, uf TEXT, regiao TEXT, municipio TEXT,
  ano_fat INTEGER, qualidade TEXT, situacao_nome TEXT, f_razao INTEGER, f_djen INTEGER, f_cvm INTEGER,
  em_insolvencia INTEGER, em_rj INTEGER, grupo_afetado INTEGER, contagio INTEGER);
CREATE TABLE IF NOT EXISTS estat(chave TEXT PRIMARY KEY, valor TEXT, atualizado REAL);
CREATE TABLE IF NOT EXISTS psi_casos(id INTEGER PRIMARY KEY, identificacao TEXT, setor TEXT, uf TEXT, data_concessao TEXT,
  data_pedido_rj TEXT, modalidade TEXT, valor_mil REAL, garantias TEXT, rating TEXT, premissas TEXT, evidencia TEXT);
CREATE TABLE IF NOT EXISTS psi_indicadores(id INTEGER PRIMARY KEY, caso_id INTEGER, indicador TEXT, v_concessao REAL, v_pre_rj REAL, considerado TEXT, evidencia TEXT);
CREATE TABLE IF NOT EXISTS psi_fatores(id INTEGER PRIMARY KEY, caso_id INTEGER, fator TEXT, categoria TEXT, presente TEXT, tratamento TEXT, impacto INTEGER, evidencia TEXT);
CREATE TABLE IF NOT EXISTS psi_recomendacoes(id INTEGER PRIMARY KEY, recomendacao TEXT, processo TEXT, impacto INTEGER, aplicabilidade INTEGER, casos TEXT, status TEXT);
CREATE INDEX IF NOT EXISTS ix_cred_proc ON credores(processo);
CREATE INDEX IF NOT EXISTS ix_partes_proc ON partes(processo);
CREATE INDEX IF NOT EXISTS ix_partes_raiz ON partes(raiz);
CREATE INDEX IF NOT EXISTS ix_djen_proc ON djen_publicacoes(processo);
CREATE INDEX IF NOT EXISTS ix_cart_grupo ON carteira(raiz_grupo);
"""

TABELAS_PUBLICAS = ["coleta_execucoes", "datajud_mensal", "datajud_varas", "datajud_processos", "djen_publicacoes", "djen_editais", "credores",
                    "cvm_insolvencia", "macro_mensal", "focus", "curva", "curva_mensal", "processos", "partes", "grupos"]
TABELAS_RESTRITAS = ["carteira", "psi_casos", "psi_indicadores", "psi_fatores", "psi_recomendacoes"]


def conectar(caminho):
    c = sqlite3.connect(caminho, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def sis():
    return conectar(DB_SISTEMA)


def ana():
    return conectar(DB_ANALITICO)


def inicializar():
    with sis() as c:
        c.executescript(SCHEMA_SISTEMA)
        for cod, nome, rec in PLANOS:
            c.execute("INSERT OR IGNORE INTO planos(codigo,nome,recursos) VALUES(?,?,?)", (cod, nome, json.dumps(rec)))
    with ana() as c:
        c.executescript(SCHEMA_ANALITICO)


def expurgar_restritos():
    """Edição pública: garante que nenhum dado interno (carteira, PSI) exista no servidor."""
    n = 0
    with ana() as c:
        for t in TABELAS_RESTRITAS:
            n += c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM estat WHERE chave LIKE 'carteira%'")
    if n:
        c = conectar(DB_ANALITICO); c.isolation_level = None; c.execute("VACUUM"); c.close()
    return n


def auditar(acao, usuario=None, ip=None, detalhe=None):
    """Registro encadeado por hash: qualquer alteração/remoção posterior quebra a cadeia."""
    det = json.dumps(detalhe, ensure_ascii=False, default=str)[:2000] if detalhe is not None else ""
    with _lock, sis() as c:
        ult = c.execute("SELECT hash FROM auditoria ORDER BY id DESC LIMIT 1").fetchone()
        ant = ult["hash"] if ult else "0" * 64
        q = time.time()
        uid = usuario["id"] if usuario else None
        lg = usuario["login"] if usuario else None
        h = hashlib.sha256(f"{ant}|{q:.6f}|{uid}|{lg}|{ip}|{acao}|{det}".encode()).hexdigest()
        c.execute("INSERT INTO auditoria(quando,usuario_id,login,ip,acao,detalhe,hash_anterior,hash) VALUES(?,?,?,?,?,?,?,?)",
                  (q, uid, lg, ip, acao, det, ant, h))


def verificar_cadeia():
    with sis() as c:
        ant, n = "0" * 64, 0
        for r in c.execute("SELECT * FROM auditoria ORDER BY id"):
            h = hashlib.sha256(f"{ant}|{r['quando']:.6f}|{r['usuario_id']}|{r['login']}|{r['ip']}|{r['acao']}|{r['detalhe']}".encode()).hexdigest()
            if r["hash_anterior"] != ant or r["hash"] != h:
                return {"integra": False, "registro_divergente": r["id"], "verificados": n}
            ant = r["hash"]; n += 1
        return {"integra": True, "verificados": n}


def estat_set(chave, valor):
    with ana() as c:
        c.execute("INSERT OR REPLACE INTO estat VALUES(?,?,?)", (chave, json.dumps(valor, ensure_ascii=False, default=str), time.time()))


def estat_get(chave, padrao=None):
    with ana() as c:
        r = c.execute("SELECT valor FROM estat WHERE chave=?", (chave,)).fetchone()
        return json.loads(r["valor"]) if r else padrao
