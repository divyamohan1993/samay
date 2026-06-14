# SAMAY / pqcsched demo service — CPU-only, multi-stage, non-root.
# No secrets in any layer; all runtime config via env. Cloud Run injects $PORT.
FROM python:3.12-slim AS build
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip wheel \
 && pip wheel --no-cache-dir --wheel-dir /wheels ".[api]"

FROM python:3.12-slim
# non-root runtime user
RUN useradd -m -u 10001 app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
USER app
ENV PORT=8080 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
# single uvicorn worker (CP-SAT parallelises internally); Cloud Run bounds
# concurrency/instances. Healthcheck hits the shallow endpoint.
HEALTHCHECK --interval=30s --timeout=4s --retries=3 \
  CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/health',timeout=3)" || exit 1
CMD ["sh","-c","uvicorn pqcsched.api:app --host 0.0.0.0 --port ${PORT} --workers 1"]
