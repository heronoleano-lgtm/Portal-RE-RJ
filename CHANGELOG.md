# Histórico

## 9.0.0 – cruzamento de bases e portal com cadastro
- Removida a integração ABJ/BigQuery (acesso não verificado); Observatório da Insolvência mantido como referência.
- Nova etapa de cruzamento: consulta do DataJud por número de processo, tabelas de processos, partes e grupos, ligação com CVM e carteira.
- Novas estatísticas: tempos até deferimento, vara especializada × comum (Mann-Whitney), Kaplan-Meier da convolação, litisconsórcio, recorrência, bancos recorrentes.
- Portal: prévia livre + cadastro do interessado ao fim da prévia (aplicado no servidor); páginas Processos e partes, Como coletamos e Privacidade.
- Administração: tela Interessados (lista, perfis, CSV, exclusão, regras e retenção).
- Comando único `atualizar` (coleta → cruzamento → estatística). 26 testes.

## 8.0.0 – projeto unificado (portal + bases ABJ)
## 7.0.0 – portal público e estatística avançada
## 6.0.0 – portabilidade e publicação
## 5.0.0 – reconstrução sem dependências, autenticação, SAC, correção de rede
## 1.0.0 – 4.0.0 – coletores, extração de credores, estatística, painel inicial
