# Controles de segurança

**Aplicação**: back-end e front-end separados; rotas do mantenedor respondem 404 aos demais (tentativas auditadas); `mnt.js` só é entregue
ao mantenedor; erros mostram mensagem neutra + código, detalhes só no log; arquivos estáticos de lista fechada.

**Identidade e sessão**: PBKDF2-SHA256 (600 mil iterações); senha 12+ com 4 classes; TOTP obrigatório para o mantenedor; códigos de
recuperação guardados como hash; cookie `HttpOnly; SameSite=Strict` (`Secure` em HTTPS); expiração 8 h ou 30 min ocioso; CSRF + origem;
limite por IP e por conta; bloqueio após 8 falhas.

**Cadastro de interessados**: consentimento obrigatório (texto gravado com o cadastro); token aleatório de 256 bits em cookie `HttpOnly;
SameSite=Lax`, no banco só o hash; validade configurável; apagamento automático após o prazo de retenção sem acesso; limite de 5 cadastros/h
por IP; campo-isca contra robôs; exclusão a pedido pela administração; exportação CSV com neutralização de fórmulas. O IP é guardado só
como hash parcial.

**Navegador**: CSP sem scripts externos ou inline; `frame-ancestors 'none'`; `nosniff`; `no-referrer`; HSTS em HTTPS; dados inseridos só
com `textContent`.

**Dados exibidos**: pessoas físicas nunca identificadas (credor PF = "PESSOA FÍSICA"; destinatário sem característica de empresa não tem
o nome gravado); edição pública sem carteira/PSI (bloqueio, recusa de importação e expurgo na inicialização – coberto por testes).
