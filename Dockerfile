# VaaniAgent streaming interpreter (vaani/stream). The desktop agent is not in the image.
FROM python:3.13-slim
WORKDIR /app
COPY requirements-stream.txt .
RUN pip install --no-cache-dir -r requirements-stream.txt
COPY vaani/__init__.py vaani/sarvam_client.py vaani/budget.py ./vaani/
COPY vaani/stream ./vaani/stream
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"
# SARVAM_API_KEY is passed at run time (-e), never baked into the image
ENTRYPOINT ["python", "-m", "vaani.stream.server", "--port", "8000", "--log-dir", "/app/logs", "--max-credits", "8"]
