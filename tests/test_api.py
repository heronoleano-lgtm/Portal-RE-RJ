"""Ponta a ponta: sobe o servidor em processo separado (edições interna e pública) com dados temporários."""
import gzip, http.cookiejar, json, os, socket, subprocess, sys, tempfile, time, unittest, urllib.request
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "backend"))


def _porta():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Servidor:
    def __init__(self, edicao):
        self.dir = tempfile.mkdtemp(); self.porta = _porta()
        env = dict(os.environ, MOTOR_DADOS_DIR=self.dir, MOTOR_EDICAO=edicao, MOTOR_PORTA=str(self.porta), MOTOR_HOST="127.0.0.1")
        code = ("import sys,time;sys.path.insert(0,'backend');from app import db,seguranca as S;db.inicializar();"
                "seg=S.novo_segredo_totp();open(sys.argv[1],'w').write(seg);"
                "c=db.sis();c.execute(\"INSERT INTO usuarios(login,nome,email,senha,papel,totp,criado) VALUES('mnt','M','m@x.com',?,'mantenedor',?,?)\",(S.hash_senha('Senha#Forte2026'),seg,time.time()));"
                "c.execute(\"INSERT INTO usuarios(login,nome,email,senha,papel,criado) VALUES('ana','A','a@x.com',?,'usuario',?)\",(S.hash_senha('Senha#Forte2026'),time.time()));"
                "c.execute(\"INSERT INTO assinaturas(usuario_id,plano,inicio,fim) VALUES(2,'corporativo',?,?)\",(time.time(),time.time()+9e6));c.commit();"
                "a=db.ana();a.execute(\"INSERT INTO estat VALUES('processos',?,0)\",('{\"total\":3,\"lista\":[{\"processo\":\"1\"}],\"por_tipo\":[]}',));"
                "a.execute(\"INSERT INTO estat VALUES('atualizado_em','\\\"x\\\"',0)\");a.commit()")
        self.seg_arq = os.path.join(self.dir, "seg")
        subprocess.run([sys.executable, "-c", code, self.seg_arq], cwd=RAIZ, env=env, check=True)
        self.p = subprocess.Popen([sys.executable, "backend/cli.py", "iniciar"], cwd=RAIZ, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                urllib.request.urlopen(self.url("/api/v1/sessao"), timeout=1); break
            except Exception:
                time.sleep(0.2)

    def url(self, p): return f"http://127.0.0.1:{self.porta}{p}"

    def parar(self): self.p.terminate(); self.p.wait(5)

    def req(self, op, p, corpo=None, csrf=None, cab=None, metodo=None):
        h = {"Content-Type": "application/json", "Origin": self.url("")}; h.update(cab or {})
        if csrf: h["X-CSRF"] = csrf
        r = urllib.request.Request(self.url(p), data=json.dumps(corpo).encode() if corpo is not None else None, headers=h, method=metodo or ("POST" if corpo is not None else "GET"))
        try:
            x = op.open(r); b = x.read()
            if x.headers.get("Content-Encoding") == "gzip": b = gzip.decompress(b)
            return x.status, (json.loads(b) if b and "json" in (x.headers.get("Content-Type") or "") else {}), x.headers
        except urllib.error.HTTPError as e:
            b = e.read(); return e.code, (json.loads(b) if b else {}), e.headers

    def cliente(self):
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def entrar(self, login):
        from app.seguranca import _hotp
        op = self.cliente()
        corpo = {"login": login, "senha": "Senha#Forte2026"}
        if login == "mnt":
            with open(self.seg_arq) as f:
                corpo["codigo"] = _hotp(f.read(), int(time.time() // 30))
        st, d, _ = self.req(op, "/api/v1/entrar", corpo)
        return op, d


CADASTRO = {"nome": "Maria Teste", "email": "maria@exemplo.com", "perfil": "Pesquisa acadêmica", "consentimento": True}


class Portal(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.s = Servidor("interna")

    @classmethod
    def tearDownClass(cls): cls.s.parar()

    def test_resumo_livre_e_demais_em_previa(self):
        op = self.s.cliente()
        self.assertEqual(self.s.req(op, "/api/v1/publico/resumo")[0], 200)
        self.assertEqual(self.s.req(op, "/api/v1/publico/coleta")[0], 200)
        st, d, h = self.s.req(op, "/api/v1/publico/processos")
        self.assertTrue(d.get("previa")); self.assertNotIn("lista", d)
        self.assertIn("private", h["Cache-Control"])

    def test_cadastro_libera_conteudo_no_servidor(self):
        op = self.s.cliente()
        self.assertEqual(self.s.req(op, "/api/v1/publico/cadastro", dict(CADASTRO, consentimento=False))[0], 400)   # sem consentimento
        self.assertEqual(self.s.req(op, "/api/v1/publico/cadastro", dict(CADASTRO, email="x"))[0], 400)            # e-mail inválido
        st, d, h = self.s.req(op, "/api/v1/publico/cadastro", CADASTRO)
        self.assertEqual(st, 200); self.assertIn("HttpOnly", h["Set-Cookie"])
        st, d, _ = self.s.req(op, "/api/v1/publico/processos")
        self.assertNotIn("previa", d); self.assertEqual(d["total"], 3)
        self.assertTrue(self.s.req(op, "/api/v1/sessao")[1]["liberado"])
        self.s.req(op, "/api/v1/publico/cadastro/sair", {})
        self.assertTrue(self.s.req(op, "/api/v1/publico/processos")[1].get("previa"))

    def test_usuario_restrito_ve_completo_e_mantenedor_ve_cadastros(self):
        op, d = self.s.entrar("ana")
        self.assertNotIn("previa", self.s.req(op, "/api/v1/publico/processos")[1])
        self.assertEqual(self.s.req(op, "/api/v1/mnt/interessados")[0], 404)
        mop, md = self.s.entrar("mnt")
        self.s.req(self.s.cliente(), "/api/v1/publico/cadastro", dict(CADASTRO, email="outro@exemplo.com"))
        lst = self.s.req(mop, "/api/v1/mnt/interessados")[1]["lista"]
        self.assertTrue(any(x["email"] == "outro@exemplo.com" for x in lst))
        st, r, _ = self.s.req(mop, "/api/v1/mnt/portal", {"exigir_cadastro": False, "validade_cadastro_dias": 30, "retencao_dias": 365}, md["csrf"])
        self.assertEqual(st, 200)
        self.assertNotIn("previa", self.s.req(self.s.cliente(), "/api/v1/publico/processos")[1])
        self.s.req(mop, "/api/v1/mnt/portal", {"exigir_cadastro": True, "validade_cadastro_dias": 180, "retencao_dias": 730}, md["csrf"])

    def test_seguranca_basica(self):
        op, d = self.s.entrar("ana")
        self.assertEqual(self.s.req(op, "/api/v1/mnt/resumo")[0], 404)
        self.assertEqual(self.s.req(op, "/api/v1/conta/sessoes/encerrar", {})[0], 403)          # sem CSRF
        self.assertEqual(self.s.req(self.s.cliente(), "/api/v1/painel/carteira")[0], 401)
        r = urllib.request.urlopen(self.s.url("/"))
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
        for p in ("/static/../backend/app/config.py", "/../dados/sistema.db", "/static/mnt.js"):
            self.assertEqual(self.s.req(self.s.cliente(), p)[0], 404)
        o = self.s.cliente()
        rq = urllib.request.Request(self.s.url("/api/v1/publico/cadastro"), data=json.dumps(CADASTRO).encode(),
                                    headers={"Content-Type": "application/json", "Origin": "http://outro-site.com"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError):
            o.open(rq)

    def test_etag_e_gzip(self):
        op = self.s.cliente()
        _, _, h = self.s.req(op, "/api/v1/publico/resumo")
        self.assertEqual(self.s.req(op, "/api/v1/publico/resumo", cab={"If-None-Match": h["ETag"]})[0], 304)
        r = op.open(urllib.request.Request(self.s.url("/vendor/plotly.min.js"), headers={"Accept-Encoding": "gzip"}))
        self.assertEqual(r.headers.get("Content-Encoding"), "gzip")


class Publica(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.s = Servidor("publica")

    @classmethod
    def tearDownClass(cls): cls.s.parar()

    def test_conteudo_restrito_inexistente(self):
        op, d = self.s.entrar("ana")
        self.assertNotIn("carteira", d["recursos"]); self.assertNotIn("psi", d["recursos"])
        self.assertEqual(self.s.req(op, "/api/v1/painel/carteira")[0], 400)
        mop, md = self.s.entrar("mnt")
        self.assertEqual(self.s.req(mop, "/api/v1/mnt/atacado", {}, md["csrf"])[0], 400)


if __name__ == "__main__":
    unittest.main()
