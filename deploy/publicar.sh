#!/usr/bin/env sh
# Executar NO SERVIDOR WEB (Linux com Docker), dentro da pasta deploy/.
set -e
cd "$(dirname "$0")"
[ -f .env ] || { echo "Crie deploy/.env a partir de .env.exemplo (DOMINIO e EMAIL_TLS)."; exit 1; }
docker compose up -d --build
echo "Subindo... aguarde 20 s"; sleep 20
docker compose ps
echo
echo "Próximos passos:"
echo "  1) Conta do mantenedor:  docker compose run --rm -it motor python backend/cli.py mantenedor"
echo "  2) Primeira carga:       docker compose exec motor python backend/cli.py atualizar"
echo "  3) Atualização periódica (cron do servidor), por exemplo diária às 3h:"
echo "     0 3 * * * cd $(pwd) && docker compose exec -T motor python backend/cli.py atualizar >> atualizacao.log 2>&1"
