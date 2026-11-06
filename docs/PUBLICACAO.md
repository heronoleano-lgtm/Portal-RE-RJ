# Outro computador, atualização e publicação

## Rodar
Python 3.9+. `DIAGNOSTICO_REDE.bat` → `CONFIGURAR_MANTENEDOR.bat` → `ATUALIZAR_TUDO.bat` → `INICIAR.bat`
(Linux/Mac: `./diagnostico.sh`, `./mantenedor.sh`, `./atualizar.sh`, `./iniciar.sh`). Rede com proxy: `config/proxy_local.bat.exemplo`.

## Atualização periódica
O comando `atualizar` executa coleta → cruzamento → estatística; o portal passa a servir o resultado na próxima visita.
- Windows: Agendador de Tarefas chamando `ATUALIZAR_TUDO.bat`.
- Servidor Linux/Docker: `cron`, por exemplo `0 3 * * * cd /caminho/deploy && docker compose exec -T motor python backend/cli.py atualizar`.

## Publicar
1. No servidor Linux com Docker: `cd deploy && cp .env.exemplo .env` (DOMINIO, EMAIL_TLS) → `./publicar.sh`.
2. `docker compose run --rm -it motor python backend/cli.py mantenedor`
3. `docker compose exec motor python backend/cli.py atualizar` (ou levar `dados/publicacao/analitico_publico.db` gerado por `EXPORTAR_PARA_WEB.bat` e rodar `importar-publico`).
4. Administração › Interessados: preencher **Responsável pelos dados** e **E-mail para pedidos sobre dados pessoais** (aparecem na página Privacidade).

## Antes de abrir ao público
- Revisar o texto da página Privacidade com quem responderá pelos dados (LGPD).
- Backup agendado (`cli.py backup`) com cópia fora do servidor – contém os cadastros.
- Confirmar com a área de integridade e a gestão se há impedimento para um portal externo sobre o tema; usar só dados públicos e nenhuma marca institucional.
