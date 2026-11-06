# API v1 (JSON) – base `/api/v1`, sem CORS; escritas exigem mesma origem (+ `X-CSRF` com sessão)

| Método | Rota | Acesso | Descrição |
|---|---|---|---|
| GET | /publico/resumo · /publico/coleta · /publico/privacidade | livre | Indicadores e gráfico principal; status e volume da coleta; regras de privacidade |
| GET | /publico/tendencia · macro · credores · processos | livre (prévia) / cadastro ou sessão (completo) | Conteúdo do portal |
| POST | /publico/cadastro · /publico/cadastro/sair | livre | Cadastro de interessado (5/h por IP) e encerramento no navegador |
| POST | /sac/contato | livre | Fale conosco (5/h por IP) |
| POST | /entrar · /sair · GET /sessao | livre/sessão | Autenticação (senha + TOTP); `/sessao` informa `liberado` |
| GET/POST | /conta/* | sessão | Senha, 2FA, sessões, assinatura |
| GET | /painel/carteira | permissão `carteira` (edição interna) | Carteira Atacado + clientes com processo |
| GET/POST/DELETE | /psi/* | permissão `psi` (edição interna) | Produção temática |
| GET | /exportar/credores · vigilancia · processos | permissão `exportar` | CSV |
| * | /mnt/* | mantenedor (404 para os demais) | Administração, incluindo /mnt/interessados e /mnt/portal |
