"""Gera docs/MANIFESTO.sha256 (integridade dos arquivos entregues). Rodar ao publicar nova versão."""
import hashlib, os
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
linhas = []
for base in ("backend", "frontend", "scripts"):
    for d, _, fs in os.walk(os.path.join(R, base)):
        if "__pycache__" in d:
            continue
        for f in sorted(fs):
            p = os.path.join(d, f); rel = os.path.relpath(p, R).replace("\\", "/")
            linhas.append(f"{hashlib.sha256(open(p, 'rb').read()).hexdigest()}  {rel}")
open(os.path.join(R, "docs", "MANIFESTO.sha256"), "w", encoding="utf-8").write("\n".join(sorted(linhas, key=lambda l: l.split('  ')[1])) + "\n")
print(len(linhas), "arquivos")
