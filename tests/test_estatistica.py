"""Valida as rotinas estatísticas contra valores de referência (statsmodels 0.15 / SciPy) e propriedades conhecidas."""
import math, os, random, sys, tempfile, unittest
os.environ.setdefault("MOTOR_DADOS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.estatistica import _irls, p_qui2, p_F       # noqa: E402
from app import analise_avancada as AA                # noqa: E402

Y = [13, 3, 7, 6, 8, 3, 5, 4, 2, 6, 9, 6, 6, 5, 12, 3, 1, 6, 3, 5, 3, 6, 8, 7, 3, 9, 2, 3, 2, 5, 3, 5, 1, 13, 3, 7, 9, 3, 1, 3, 2, 3, 0, 2, 2, 4, 11, 8, 1, 2, 11, 4, 8, 3, 4, 6, 5, 4, 3, 3, 3, 4, 8, 2, 4, 3, 10, 6, 3, 5, 1, 5, 9, 7, 5, 1, 3, 8, 3, 3, 4, 3, 5, 2, 3, 5, 1, 6, 3, 4, 7, 8, 1, 2, 4, 5, 4, 5, 2, 6, 4, 2, 4, 2, 9, 4, 11, 2, 7, 1, 1, 11, 1, 1, 8, 10, 2, 2, 3, 5, 3, 4, 5, 11, 16, 4, 5, 8, 9, 5, 12, 7, 10, 4, 6, 1, 0, 5, 1, 0, 3, 3, 7, 5, 16, 11, 13, 1, 9, 5, 3, 2, 6, 5, 5, 5, 2, 6, 2, 3, 4, 10, 1, 3, 10, 3, 6, 5, 9, 1, 8, 9, 1, 12, 16, 7, 1, 2, 5, 1, 2, 4, 9, 0, 3, 4, 2, 2, 5, 2, 3, 5, 4, 6, 5, 3, 3, 5, 6, 10]


class Referencia(unittest.TestCase):
    def test_glm_binomial_negativo_igual_statsmodels(self):
        X = [[1.0, float(i % 7) / 7, float((i * 37) % 11) / 11] for i in range(len(Y))]
        b, ep, _ = _irls(X, Y, [1] * len(Y), "nb", 0.25)
        for a, r in zip(b, [1.684955, 0.182615, -0.393426]):
            self.assertAlmostEqual(a, r, places=5)
        for a, r in zip(ep, [0.111298, 0.16731, 0.166051]):
            self.assertAlmostEqual(a, r, places=5)

    def test_pvalores(self):
        self.assertAlmostEqual(p_qui2(7.3, 3), 0.0629262364, places=8)
        self.assertAlmostEqual(p_F(2.4, 4, 100), 0.0549818329, places=8)

    def test_wilson(self):
        self.assertEqual(AA.wilson(10, 100), (5.52, 17.44))

    def test_mann_whitney_igual_scipy(self):
        a = [12, 15, 9, 20, 14, 11, 18, 13, 16, 10, 22, 14]
        b = [25, 30, 19, 28, 24, 35, 27, 21, 26, 33, 29, 24, 31]
        u, p = AA.mann_whitney(a, b)
        self.assertEqual(u, 3.0)
        self.assertAlmostEqual(p, 5.038686214195715e-05, places=10)


class Propriedades(unittest.TestCase):
    def test_gini_e_hhi(self):
        self.assertEqual(AA.gini([5, 5, 5, 5]), 0.0)
        self.assertAlmostEqual(AA.gini([0, 0, 0, 1]), 0.75, places=4)
        self.assertEqual(AA.hhi([50, 50]), 5000.0)
        self.assertEqual(AA.faixa_hhi(1400), "baixa")

    def test_lorenz_monotona(self):
        lz = AA.lorenz([1, 2, 3, 10, 50])
        self.assertEqual(lz[-1]["valor"], 1.0)
        self.assertTrue(all(a["valor"] <= b["valor"] for a, b in zip(lz, lz[1:])))

    def test_pontos_de_quebra_recupera_regimes(self):
        rnd = random.Random(2)
        y = [int(rnd.gauss(90, 9)) for _ in range(50)] + [int(rnd.gauss(150, 12)) for _ in range(40)]
        q = AA.pontos_de_quebra(y)
        self.assertEqual(len(q["regimes"]), 2)
        self.assertLessEqual(abs(q["quebras"][0] - 50), 2)

    def test_decomposicao_recupera_sazonalidade(self):
        y = [100 * (1 + 0.2 * math.sin(2 * math.pi * (t % 12) / 12)) for t in range(72)]
        d = AA.decompor(y)
        self.assertAlmostEqual(d["indices"][3], 1.2, delta=0.02)
        self.assertAlmostEqual(sum(d["indices"]), 12, places=6)

    def test_holt_winters_e_validacao(self):
        rnd = random.Random(4)
        y = [max(1, 100 + 0.5 * t + 20 * math.sin(2 * math.pi * t / 12) + rnd.gauss(0, 4)) for t in range(96)]
        hw = AA.holt_winters(y, 12)
        self.assertEqual(len(hw["previsao"]), 12)
        self.assertTrue(all(p["inf"] < p["previsto"] < p["sup"] for p in hw["previsao"]))
        cv = AA.validacao_cruzada(y, {"hw": lambda tr, h: [p["previsto"] for p in AA.holt_winters(tr, h)["previsao"]], "ing": AA.ingenuo_sazonal})
        self.assertLess(cv["hw"]["MASE"], 1.0)

    def test_kaplan_meier(self):
        km = AA.kaplan_meier([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], [1, 1, 1, 1, 1, 0, 0, 0, 0, 0])
        self.assertEqual(km["eventos"], 5)
        self.assertAlmostEqual(km["curva"][-1]["s"], 0.5, places=4)


if __name__ == "__main__":
    unittest.main()
