# ADR 0002 – Portal público e área restrita no mesmo código
**Decisão:** conteúdo público em `/api/v1/publico/*`; conteúdo interno exige sessão e permissão; a edição pública desliga carteira/PSI
no servidor, recusa importação e apaga dados internos ao iniciar.
