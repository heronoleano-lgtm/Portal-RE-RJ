import os, sys, tempfile, unittest
os.environ.setdefault("MOTOR_DADOS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.coleta.credores import extrair, banco_de   # noqa: E402
from app.coleta.fontes import parse_processo        # noqa: E402

EDITAL = ("EDITAL art. 7º, § 2º relação de credores. XYZ LTDA, CNPJ 12.345.678/0001-90.<p>CLASSE I – TRABALHISTA</p><p>JOSÉ DA SILVA, CPF 123.456.789-00 – R$ 15.000,00</p>"
          "<p>CLASSE II – GARANTIA REAL</p><p>BANCO DO BRASIL S.A. – CNPJ 00.000.000/0001-91 – R$ 4.000.000,00</p><p>CLASSE III – QUIROGRAFÁRIOS</p>"
          "<table><tr><td>CAIXA ECONÔMICA FEDERAL</td><td>00.360.305/0001-04</td><td>R$ 4.970.908,45</td></tr><tr><td>EXPORT BANK</td><td></td><td>US$ 1.000.000,00</td></tr></table>"
          "<p>TOTAL CLASSE III R$ 4.970.908,45</p>")


class Credores(unittest.TestCase):
    def test_extracao(self):
        tipo, prec, lin, tots, _, cab = extrair(EDITAL)
        self.assertEqual(prec, 2)
        self.assertEqual(len(lin), 4)
        pf = [l for l in lin if l["tipo_pessoa"] == "PF"][0]
        self.assertEqual(pf["credor"], "PESSOA FÍSICA")  # LGPD
        self.assertEqual(pf["doc"], "")
        cx = [l for l in lin if l["banco"] == "CAIXA"][0]
        self.assertEqual((cx["classe"], cx["valor"]), ("III – Quirografário", 4970908.45))
        self.assertEqual([l for l in lin if l["moeda"] == "USD"][0]["banco"], "Outra instituição financeira")
        self.assertEqual(tots["III – Quirografário"], 4970908.45)
        self.assertIn("12.345.678/0001-90", cab)

    def test_banco_por_nome(self):
        self.assertEqual(banco_de("BANCO BRADESCO S/A", "")[0], "Bradesco")


class DataJudPorProcesso(unittest.TestCase):
    def test_parse_formatos_de_data_e_marcos(self):
        src = {"classe": {"codigo": 129, "nome": "Recuperação Judicial"}, "dataAjuizamento": "20230510000000",
               "orgaoJulgador": {"nome": "1ª Vara de Falências e Recuperações Judiciais", "codigoMunicipioIBGE": 3550308},
               "movimentos": [{"nome": "Distribuição", "dataHora": "2023-05-10T10:00:00.000Z"},
                              {"nome": "Deferimento do processamento da recuperação judicial", "dataHora": "2023-06-01T12:00:00.000Z"},
                              {"nome": "Concessão da Recuperação Judicial", "dataHora": "20240215000000"}]}
        r = parse_processo(src)
        self.assertEqual((r["classe_codigo"], r["ajuizamento"], r["dt_deferimento"], r["dt_concessao"]), (129, "2023-05-10", "2023-06-01", "2024-02-15"))
        self.assertIsNone(r["dt_convolacao"])
        self.assertEqual(r["dt_ultima_mov"], "2024-02-15")


if __name__ == "__main__":
    unittest.main()
