# Immagine dell'applicazione (sviluppo e produzione: deploy/docker-compose.prod.yml).
FROM python:3.12-slim-bookworm AS build

RUN pip install --no-cache-dir uv==0.8.17 \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential libldap2-dev libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends libldap-2.5-0 tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 1000 --home-dir /app app

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH \
    DJANGO_SETTINGS_MODULE=config.settings.prod TZ=Europe/Rome
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=app:app . .
RUN mkdir /app/staticfiles && chown app:app /app/staticfiles
USER app
# File statici dentro l'immagine: li serve l'app (WhiteNoise), coerenti con la versione.
# Variabili fittizie: collectstatic non usa né il database né la chiave.
RUN DJANGO_SECRET_KEY=solo-build DATABASE_URL=postgres://build@localhost/build \
    python manage.py collectstatic --noinput >/dev/null

EXPOSE 8000
# Il controllo usa il primo host ammesso: con un Host non ammesso Django risponde 400.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os,sys,urllib.request as u; h=(os.environ.get('DJANGO_ALLOWED_HOSTS') or 'localhost').split(',')[0].strip(); h='localhost' if h in ('', '*') else ('www'+h if h.startswith('.') else h); r=u.Request('http://127.0.0.1:8000/healthz', headers={'Host': h, 'X-Forwarded-Proto': 'https'}); sys.exit(u.urlopen(r, timeout=4).status != 200)"
# Opzioni di gunicorn da GUNICORN_CMD_ARGS (la riga di comando le sovrascriverebbe).
ENV GUNICORN_CMD_ARGS="--workers 3 --timeout 60"
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--access-logfile", "-"]
