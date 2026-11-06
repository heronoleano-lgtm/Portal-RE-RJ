# ADR 0004 – Remoção da integração ABJ/BigQuery
**Contexto:** não havia identificação verificada das tabelas da ABJ no BigQuery nem acesso confirmado; manter a funcionalidade exigiria suposições.
**Decisão:** remover módulo, telas, atalhos e testes. O Observatório da Insolvência segue apenas como referência metodológica.
**Consequências:** o portal usa somente fontes com acesso documentado (CNJ, CVM, BCB, Tesouro). Se uma base da ABJ for disponibilizada
de forma verificável no futuro, entra como nova etapa de coleta.
