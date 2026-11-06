# Revisão 9.0 – análise do que foi construído e do que mudou

## 1. Diagnóstico da versão 8
| Ponto | Situação na v8 | Problema |
|---|---|---|
| Bases ABJ via BigQuery | módulo, tela, testes e scripts próprios | Não havia identificação verificada das tabelas da ABJ no BigQuery nem caminho de acesso confirmado; a funcionalidade dependia de suposições. |
| "Partes" e "processos" | existiam só como colunas soltas (DJEN, editais) | Não havia uma etapa que **cruzasse** as bases; o portal mostrava contagens e credores, mas não processos identificados com partes, marcos e grupos. |
| DataJud | usado só para contagens agregadas | Não era consultado **processo a processo**, embora a API permita (consulta por `numeroProcesso`). |
| Portal | todo o conteúdo aberto | Sem captação de interessados; sem página dedicada a explicar a coleta. |
| Pipeline | coleta e estatística separadas | Faltava um comando único "coletar → cruzar → calcular → publicar". |

## 2. O que foi feito
### Removido
- Toda a integração com a ABJ por BigQuery (módulo, rotas, tela, atalhos, scripts, testes e documentação).
- O Observatório da Insolvência (ABJ/NEPI PUC-SP) **permanece como referência metodológica**, como já era: download opcional do relatório público, sem entrar nos cálculos.

### Novo fluxo de dados
```
APIs públicas ─► coleta ─► cruzamento ─► estatística ─► portal
DataJud (contagens)        processos         séries, previsão       prévia livre
DJEN (publicações)   ─►    partes       ─►   tempos processuais ─►  + cadastro
DJEN (editais)             grupos            credores, HHI          + conteúdo completo
DataJud (por processo)                       macro, curva de juros
CVM · BCB · Tesouro
```
Comando único: `ATUALIZAR_TUDO.bat` (ou `python backend/cli.py atualizar`).

### Cruzamento (`backend/app/integracao.py`)
1. **Processos**: todo número de processo encontrado no DJEN ou em editais vira um registro; o DataJud é consultado para cada um (classe, ajuizamento, órgão julgador, movimentos).
2. **Partes**: devedoras (CNPJ no cabeçalho do edital), credoras (lista do edital), destinatárias PJ das publicações e CNPJs citados.
3. **Grupos**: empresas ligadas por aparecerem juntas como devedoras (litisconsórcio) ou em mais de um processo.
4. **CVM**: marca companhias abertas com situação de insolvência.
5. **Carteira (edição interna)**: clientes cuja raiz de CNPJ aparece entre as partes.

Regras de prudência, para não inventar informação: devedora só pelo cabeçalho do edital; demais CNPJs ficam como "citados"; tipo do processo pela classe oficial; datas processuais pelo texto do movimento; pessoas físicas sem nome gravado.

### Novas estatísticas
Mediana de dias até o deferimento (geral e por UF), vara especializada × comum (Mann-Whitney, validado contra SciPy),
permanência sem convolação em falência (Kaplan-Meier com censura), litisconsórcio, empresas recorrentes, bancos credores
mais recorrentes, companhias abertas com processo.

### Portal
- **Prévia livre** em todas as páginas (indicadores, gráfico principal e leitura rápida na visão geral; um gráfico nas demais).
- Ao rolar até o fim da prévia, abre o **cadastro** (nome, e-mail, perfil, organização e interesse opcionais, consentimento obrigatório, opção de avisos).
- A liberação é feita **no servidor** (sem cadastro as rotas devolvem só a prévia) – não é contornável pelo navegador.
- Nova página **Processos e partes**, página **Como coletamos** (fluxo, fontes, última execução e volume de cada base, regras do cruzamento, métodos, limitações) e página **Privacidade**.
- Administração: tela **Interessados** (lista, perfis, exportação CSV, exclusão a pedido, regras do cadastro).

### Mantido (sem perdas)
Edições interna/pública, carteira Atacado, PSI 15508, credores e concentração, macro e curva de juros, previsão por ensemble,
SAC, usuários, assinaturas, auditoria encadeada, 2FA, proxy/PAC/certificado corporativo, exportação pública, backup, Docker/Caddy.

## 3. Qualidade
26 testes automatizados (estatística vs. statsmodels/SciPy, parser de credores, leitura do DataJud por processo,
cruzamento, cadastro aplicado no servidor, segurança, edição pública).

## 4. Pontos que dependem de execução real
- O nome dos movimentos varia entre tribunais; as datas de deferimento/concessão/convolação devem ser conferidas por amostra após a primeira coleta real.
- A quantidade de processos identificados depende da janela de dias do DJEN (`djen.dias`, `djen.dias_credores`) e do limite de consultas por execução (`datajud.enriquecer_max`).
