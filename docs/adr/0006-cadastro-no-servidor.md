# ADR 0006 – Cadastro de interessados aplicado no servidor
**Decisão:** sem cadastro, as rotas devolvem só a prévia; com cadastro (cookie com token cujo hash fica no banco), o conteúdo completo.
O front-end apenas exibe o formulário ao fim da prévia.
**Consequências:** o bloqueio não é contornável pelo navegador; respostas variam por cookie (`Cache-Control: private`, `Vary: Cookie`).
