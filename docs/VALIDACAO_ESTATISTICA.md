# Validação estatística (tests/test_estatistica.py)
| Rotina | Referência | Resultado |
|---|---|---|
| GLM binomial negativo (IRLS) | statsmodels 0.15 | coeficientes e erros-padrão iguais (5 casas) |
| p-valor qui-quadrado e F (Granger) | SciPy | iguais (8 casas) |
| IC de Wilson | statsmodels `proportion_confint` | igual |
| Mann-Whitney (assintótico, empates e continuidade) | SciPy `mannwhitneyu` | U e p iguais (10 casas) |
Testes de propriedade: decomposição recupera sazonalidade; segmentação recupera a quebra; Holt-Winters supera o ingênuo; Kaplan-Meier.
