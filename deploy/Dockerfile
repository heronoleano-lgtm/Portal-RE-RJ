# Imagem mínima: só Python oficial, nenhum pacote adicional (sem pip install).
FROM python:3.12-slim
RUN useradd --create-home --uid 10001 motor
WORKDIR /app
COPY --chown=root:root backend ./backend
COPY --chown=root:root frontend ./frontend
COPY --chown=root:root docs ./docs
COPY --chown=motor:motor config ./config
RUN mkdir -p /app/dados && chown motor:motor /app/dados
USER motor
ENV MOTOR_EDICAO=publica MOTOR_HOST=0.0.0.0 MOTOR_PORTA=8750 MOTOR_HTTPS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8750
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8750/api/v1/sessao',timeout=4)"
CMD ["python", "backend/cli.py", "iniciar"]
