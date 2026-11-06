# Arquitetura – Observatório RJ/RE (9.0)

## Contexto
```
 Visitante (prévia) ─┐                          ┌── CNJ DataJud (contagens e consulta por processo)
 Interessado (cadastro) ─┤  Observatório RJ/RE  ├── CNJ DJEN (publicações e editais de credores)
 Usuário restrito ───┤   (portal + motor)       ├── CVM · Banco Central (SGS, Focus) · Tesouro
 Mantenedor ─────────┘                          └── Observatório da Insolvência (referência, GitHub)
```

## Contêineres
| Contêiner | Tecnologia | Responsabilidade |
|---|---|---|
| Proxy de borda | Caddy 2 | TLS automático, HSTS, compressão, limite de corpo, IP real |
| Aplicação | Python 3.9+ (stdlib) | API `/api/v1`, sessões, cadastro de interessados, autorização, cache |
| Motor de dados | Python (stdlib) | Coleta, cruzamento, estatística, previsão (`pipeline.processar_tudo`) |
| Front-end | HTML + JS puro + Plotly local | Portal (prévia/cadastro/completo), área restrita, administração |
| Persistência | SQLite (WAL) | `sistema.db` (identidade, auditoria, SAC, interessados) · `analitico.db` (dados, cruzamentos, resultados) |

## Camadas do back-end
```
apresentação   servidor.py ← rotas.py · rotas_publicas.py (prévia/cadastro) · rotas_mantenedor.py
aplicação      pipeline.py → coleta/fontes.py → integracao.py → estatistica.py · atacado.py
domínio        analise_avancada.py · coleta/credores.py (parser) · seguranca.py
infraestrutura db.py · rede.py (proxy/PAC/CA) · config.py
```

## Modelo de dados do cruzamento
| Tabela | Grão | Origem |
|---|---|---|
| `datajud_processos` | processo | DataJud, consulta por número |
| `partes` | processo × parte × papel | DJEN, editais, CVM |
| `processos` | processo | união de DJEN + editais + DataJud + CVM |
| `grupos` | conjunto de empresas | componentes conexos das devedoras |

## Cadastro e conteúdo
`/api/v1/publico/resumo` e `/coleta` são livres. `/tendencia`, `/macro`, `/credores` e `/processos` devolvem a **prévia**
sem cadastro e o conteúdo completo com o cookie `mrj_vis` (token aleatório; no banco só o hash) ou com sessão da área restrita.
Respostas variam por cookie → `Cache-Control: private` e `Vary: Cookie`.
