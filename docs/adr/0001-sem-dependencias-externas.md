# ADR 0001 – Núcleo sem dependências externas
**Contexto:** a rede corporativa bloqueia pip/npm; dependências ampliam a superfície de ataque.
**Decisão:** back-end só com a biblioteca padrão do Python; front-end com JavaScript puro e Plotly local.
**Consequências:** estatística reimplementada e validada por testes; implantação trivial.
