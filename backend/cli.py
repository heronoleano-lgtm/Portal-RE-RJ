"""Linha de comando do Observatório RJ/RE (sem dependências externas).
  python backend/cli.py atualizar             -> pipeline completo: coleta das APIs + cruzamento + estatística (o portal passa a exibir o resultado)
  python backend/cli.py iniciar               -> sobe o portal (http://localhost:8750)
  python backend/cli.py mantenedor            -> cria/recupera a conta do mantenedor (senha + 2FA)
  python backend/cli.py diagnostico           -> testa rotas de rede e fontes
  python backend/cli.py coletar [etapas...]   -> datajud djen credores cvm macro enriquecer observatorio (+ cruzamento e estatística)
  python backend/cli.py integrar              -> refaz só o cruzamento e a estatística (sem coletar)
  python backend/cli.py importar <arquivo.xlsx>   (edição interna)
  python backend/cli.py exportar-publico      -> dados/publicacao/analitico_publico.db (só dados públicos)
  python backend/cli.py importar-publico <arq> -> carrega o arquivo acima no servidor web
  python backend/cli.py backup                -> dados/backups/backup_AAAAMMDD_HHMM.zip
"""
import getpass, os, sys, time, secrets
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.version_info < (3, 9):
    sys.exit("Necessário Python 3.9 ou superior.")


def mantenedor():
    from app import db, seguranca as S
    db.inicializar()
    print("\n=== Conta do MANTENEDOR (acesso total; 2FA obrigatório) ===")
    login = input("Login: ").strip().lower()
    if not S.RX_LOGIN.match(login):
        sys.exit("Login inválido.")
    nome = input("Nome completo: ").strip() or login
    email = input("E-mail: ").strip()
    while True:
        s1 = getpass.getpass("Senha (mín. 12, maiúscula, minúscula, número e símbolo): ")
        erro = S.politica_senha(s1)
        if erro:
            print(" ", erro); continue
        if getpass.getpass("Repita a senha: ") != s1:
            print("  As senhas não conferem."); continue
        break
    seg = S.novo_segredo_totp()
    print("\nCadastre no app autenticador (Microsoft Authenticator, Google Authenticator...):")
    print("  Chave manual :", seg)
    print("  URI          :", S.uri_totp(seg, login))
    for _ in range(3):
        if S.confere_totp(seg, input("Digite o código de 6 dígitos exibido no app: ").strip()):
            break
        print("  Código incorreto.")
    else:
        sys.exit("2FA não confirmado. Nada foi gravado.")
    codigos = [secrets.token_hex(4).upper() for _ in range(8)]
    with db.sis() as c:
        ex = c.execute("SELECT id FROM usuarios WHERE login=?", (login,)).fetchone()
        if ex:
            c.execute("UPDATE usuarios SET nome=?, email=?, senha=?, papel='mantenedor', totp=?, ativo=1, falhas=0, bloqueado_ate=0 WHERE id=?",
                      (nome, email, S.hash_senha(s1), seg, ex["id"])); uid = ex["id"]
        else:
            uid = c.execute("INSERT INTO usuarios(login,nome,email,senha,papel,totp,criado) VALUES(?,?,?,?, 'mantenedor', ?, ?)",
                            (login, nome, email, S.hash_senha(s1), seg, time.time())).lastrowid
        c.execute("DELETE FROM recuperacao WHERE usuario_id=?", (uid,))
        c.executemany("INSERT INTO recuperacao(usuario_id,hash) VALUES(?,?)", [(uid, S.h256(k)) for k in codigos])
        c.execute("DELETE FROM sessoes WHERE usuario_id=?", (uid,))
    db.auditar("mantenedor_configurado_cli", {"id": uid, "login": login}, "local")
    print("\nCódigos de recuperação (uso único) – guarde fora do computador:\n  " + "  ".join(codigos))
    print("\nConta do mantenedor pronta.")


def exportar_publico():
    """Copia SÓ as tabelas públicas para um banco novo. Nada da carteira/PSI sai da máquina interna."""
    import sqlite3
    from app import db
    from app.config import DIR_DADOS, DB_ANALITICO
    db.inicializar()
    dst_dir = os.path.join(DIR_DADOS, "publicacao"); os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "analitico_publico.db")
    if os.path.exists(dst):
        os.remove(dst)
    with sqlite3.connect(dst) as d:
        d.executescript(db.SCHEMA_ANALITICO)
        d.execute("ATTACH DATABASE ? AS orig", (DB_ANALITICO,))
        for t in db.TABELAS_PUBLICAS:
            d.execute(f"INSERT INTO {t} SELECT * FROM orig.{t}")
        d.execute("INSERT INTO estat SELECT * FROM orig.estat WHERE chave NOT LIKE 'carteira%' AND chave<>'credores'")
        d.commit(); d.execute("DETACH DATABASE orig")
    d = sqlite3.connect(dst, isolation_level=None)
    for t in db.TABELAS_RESTRITAS:
        assert d.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
    d.execute("VACUUM"); d.close()
    print("  Arquivo para publicação:", dst)
    print("  Contém apenas: " + ", ".join(db.TABELAS_PUBLICAS))


def importar_publico(arq):
    import shutil, sqlite3
    from app import db, estatistica
    from app.config import DB_ANALITICO
    with sqlite3.connect(arq) as d:
        for t in db.TABELAS_RESTRITAS:
            if d.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]:
                sys.exit("Arquivo recusado: contém dados internos. Gere-o com 'exportar-publico'.")
    shutil.copy(arq, DB_ANALITICO)
    db.inicializar(); db.expurgar_restritos(); estatistica.montar()
    print("  Dados públicos carregados e estatística recalculada.")


def backup():
    import sqlite3, zipfile
    from app import db
    from app.config import DIR_DADOS, DB_SISTEMA, DB_ANALITICO
    db.inicializar()
    pasta = os.path.join(DIR_DADOS, "backups"); os.makedirs(pasta, exist_ok=True)
    arq = os.path.join(pasta, time.strftime("backup_%Y%m%d_%H%M.zip"))
    with zipfile.ZipFile(arq, "w", zipfile.ZIP_DEFLATED) as z:
        for orig in (DB_SISTEMA, DB_ANALITICO):
            tmp = orig + ".bkp"
            with sqlite3.connect(orig) as a, sqlite3.connect(tmp) as b:
                a.backup(b)
            z.write(tmp, os.path.basename(orig)); os.remove(tmp)
    print("  Backup:", arq)
    print("  ATENÇÃO: contém usuários, cadastros de interessados e, na edição interna, dados sigilosos. Guarde em local protegido.")


def _pipeline(etapas):
    from app import db
    from app.pipeline import processar_tudo
    db.inicializar()
    r = processar_tudo(etapas, lambda e: print(f"  > {e}", flush=True))
    for k, v in r.items():
        print(f"  {k:<14} {v}")
    print("  Portal atualizado: os dados novos aparecem na próxima visita.")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "iniciar"
    if cmd == "iniciar":
        from app.servidor import iniciar; iniciar()
    elif cmd == "mantenedor":
        mantenedor()
    elif cmd == "diagnostico":
        from app import rede
        d = rede.diagnostico()
        print("\nROTAS DE REDE TESTADAS"); [print(f"  {r['rota']:<40} {r['resultado']}") for r in d["rotas"]]
        print(f"\nRota escolhida: {d['rota_escolhida']}\n\nFONTES"); [print(f"  {f['fonte']:<38} {f['resultado']}") for f in d["fontes"]]
        if not any(r["status"] for r in d["rotas"]):
            print("\nNenhuma rota funcionou. Na rede corporativa: informe o proxy em config/proxy_local.bat (MOTOR_PROXY); "
                  "se o proxy pedir senha, defina MOTOR_PROXY_USER (a senha é pedida na abertura).")
    elif cmd == "atualizar":
        _pipeline(None)
    elif cmd == "coletar":
        from app.coleta import fontes
        etapas = sys.argv[2:] or fontes.PADRAO_COLETA
        desconhecidas = [e for e in etapas if e not in fontes.ETAPAS]
        if desconhecidas:
            sys.exit("Etapas desconhecidas: " + ", ".join(desconhecidas) + ". Válidas: " + ", ".join(fontes.ETAPAS))
        _pipeline(etapas)
    elif cmd in ("integrar", "estatistica"):
        _pipeline([])
    elif cmd == "importar":
        from app import db, atacado, estatistica
        from app.config import PUBLICA
        if PUBLICA:
            sys.exit("Edição pública: importação da base de clientes não permitida.")
        db.inicializar(); print("  CNPJs importados:", atacado.importar(sys.argv[2]))
        estatistica.carteira(); estatistica.credores()
    elif cmd == "exportar-publico":
        exportar_publico()
    elif cmd == "importar-publico":
        importar_publico(sys.argv[2])
    elif cmd == "backup":
        backup()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
