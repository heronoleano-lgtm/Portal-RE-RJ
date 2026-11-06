"""Cruzamento das bases: processos, partes, grupos; regras de prudência e exportação pública."""
import os, sqlite3, subprocess, sys, tempfile, unittest
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MOTOR_DADOS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(RAIZ, "backend"))
from app import db, integracao, estatistica    # noqa: E402

db.inicializar()
P1, P2, P3 = "10000010020248260100", "20000020020248210001", "30000030020248160001"


def _carregar():
    with db.ana() as c:
        for t in ("djen_publicacoes", "djen_editais", "credores", "datajud_processos", "cvm_insolvencia", "carteira"):
            c.execute(f"DELETE FROM {t}")
        # P1: RJ com edital (duas devedoras do mesmo grupo), DataJud com marcos
        c.execute("INSERT INTO djen_publicacoes VALUES('a','recuperação judicial','2024-03-01','TJSP',?,'1ª Vara de Falências','Intimação','Recuperação Judicial','ALFA AGRO LTDA;JOAO DA SILVA','11111111000111','')", (P1,))
        c.execute("INSERT INTO djen_editais VALUES('e1',?,'TJSP','2024-03-10','Lista do AJ (art. 7º §2º)',2,'RJ','ALFA AGRO LTDA','11111111000111;22222222000122',2,500.0,'{}','{}','Alta',0,1,NULL)", (P1,))
        c.execute("INSERT INTO credores(edital_id,processo,classe,credor,doc,tipo_pessoa,moeda,valor,banco,tipo_banco,match_banco) VALUES('e1',?,'III – Quirografário','BANCO DO BRASIL S.A','00000000000191','PJ','BRL',400,'Banco do Brasil','Público','CNPJ')", (P1,))
        c.execute("INSERT INTO credores(edital_id,processo,classe,credor,doc,tipo_pessoa,moeda,valor,banco,tipo_banco,match_banco) VALUES('e1',?,'I – Trabalhista','PESSOA FÍSICA','','PF','BRL',100,NULL,NULL,NULL)", (P1,))
        c.execute("INSERT INTO datajud_processos VALUES(?,'TJSP',129,'Recuperação Judicial','2024-01-10','1ª Vara de Falências e Recuperações Judiciais','3550308','',5,'2024-02-09',NULL,NULL,NULL,'2024-05-01',1,0)", (P1,))
        # P2: mesma empresa 22222222 em outro processo (recorrência) e companhia aberta
        c.execute("INSERT INTO djen_editais VALUES('e2',?,'TJRS','2024-04-01','Lista do devedor (art. 52 §1º)',1,'RJ','BETA S.A.','22222222000122',0,0,'{}','{}','Sem lista',0,0,NULL)", (P2,))
        c.execute("INSERT INTO cvm_insolvencia VALUES('22222222000122','BETA PARTICIPACOES S.A.','Holding','EM RECUPERAÇÃO JUDICIAL','2024-03-20','RS')")
        # P3: só publicação de RE, sem DataJud nem edital
        c.execute("INSERT INTO djen_publicacoes VALUES('b','recuperação extrajudicial','2024-05-01','TJPR',?,'2ª Vara Cível','Edital','Recuperação Extrajudicial','GAMA COMERCIO LTDA','','')", (P3,))
        c.execute("INSERT INTO carteira(cnpj,raiz,raiz_grupo,razao) VALUES('22222222000199','22222222','22222222','BETA CLIENTE')")


class Integracao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _carregar(); cls.r = integracao.integrar(); estatistica.montar()
        with db.ana() as c:
            cls.proc = {r["processo"]: dict(r) for r in c.execute("SELECT * FROM processos")}
            cls.partes = [dict(r) for r in c.execute("SELECT * FROM partes")]
            cls.grupos = [dict(r) for r in c.execute("SELECT * FROM grupos")]

    def test_processos_e_tipos(self):
        self.assertEqual(self.r["processos"], 3)
        self.assertEqual(self.proc[P1]["tipo"], "RJ")          # classe do DataJud
        self.assertEqual(self.proc[P3]["tipo"], "RE")          # classe do DJEN
        self.assertEqual(self.proc[P1]["fontes"], "DJEN;Edital;DataJud")

    def test_tempos_e_vara(self):
        self.assertEqual(self.proc[P1]["dias_deferimento"], 30)
        self.assertEqual(self.proc[P1]["vara_especializada"], 1)
        self.assertEqual(self.proc[P1]["passivo"], 500.0)
        self.assertEqual(self.proc[P1]["bancos_pct"], 80.0)

    def test_devedoras_so_do_cabecalho_e_pf_sem_nome(self):
        dev = {(p["processo"], p["cnpj"]) for p in self.partes if p["papel"] == "devedora"}
        self.assertEqual(dev, {(P1, "11111111000111"), (P1, "22222222000122"), (P2, "22222222000122")})
        self.assertFalse(any(p["nome"] and "JOAO" in p["nome"] for p in self.partes))     # destinatário PF não gravado
        self.assertTrue(any(p["papel"] == "citada" and p["cnpj"] == "11111111000111" for p in self.partes))
        self.assertEqual(self.proc[P1]["n_raizes"], 2)

    def test_grupo_por_litisconsorcio_e_recorrencia(self):
        g = [x for x in self.grupos if "22222222" in x["raizes"]][0]
        self.assertEqual((g["n_empresas"], g["n_processos"]), (2, 2))
        self.assertEqual(self.proc[P1]["grupo"], self.proc[P2]["grupo"])

    def test_cvm_nome_e_estatisticas(self):
        self.assertEqual(self.proc[P2]["cvm"], 1)
        self.assertIn("BETA PARTICIPACOES", self.proc[P2]["devedora"])
        e = db.estat_get("processos")
        self.assertEqual(e["total"], 3)
        self.assertEqual(e["litisconsorcio"]["mais_de_uma_empresa"], 1)
        self.assertEqual(e["recorrentes"][0]["processos"], 2)

    def test_carteira_cruza_com_processos(self):
        cp = db.estat_get("carteira_processos")
        self.assertEqual({x["processo"] for x in cp}, {P1, P2})

    def test_exportacao_publica_sem_carteira(self):
        r = subprocess.run([sys.executable, "backend/cli.py", "exportar-publico"], cwd=RAIZ, env=dict(os.environ), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        arq = os.path.join(os.environ["MOTOR_DADOS_DIR"], "publicacao", "analitico_publico.db")
        d = sqlite3.connect(arq)
        self.assertEqual(d.execute("SELECT COUNT(*) FROM processos").fetchone()[0], 3)
        self.assertEqual(d.execute("SELECT COUNT(*) FROM carteira").fetchone()[0], 0)
        d.close()
        with open(arq, "rb") as f:
            self.assertNotIn(b"BETA CLIENTE", f.read())


if __name__ == "__main__":
    unittest.main()
