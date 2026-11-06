"""Pipeline completo do Observatório: coletar (APIs) → cruzar (processos, partes, grupos) → carteira (edição interna)
→ estatística → portal (as rotas públicas passam a servir o resultado novo automaticamente)."""
from .config import PUBLICA
from . import db, estatistica, atacado, integracao
from .coleta import fontes


def processar_tudo(etapas=None, aviso=lambda e: None):
    etapas = fontes.PADRAO_COLETA if etapas is None else etapas
    resultado = {}
    for e in etapas:
        aviso(e)
        if e in fontes.ETAPAS:
            resultado[e] = fontes.ETAPAS[e]()
    aviso("cruzamento das bases")
    resultado["integracao"] = integracao.integrar()
    db.estat_set("integracao", resultado["integracao"])
    if not PUBLICA:
        atacado.atualizar_status()
    aviso("estatística")
    estatistica.montar()
    return resultado
