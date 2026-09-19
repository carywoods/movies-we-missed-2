FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 DATABASE_PATH=/app/data/mwm.db
WORKDIR /app
COPY pyproject.toml ./
COPY migrations ./migrations
COPY mwm ./mwm
COPY deploy/mwm-seed.db /app/seed/mwm.db
COPY deploy/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN pip install --no-cache-dir .
RUN mkdir -p /app/data && chmod 755 /app/docker-entrypoint.sh && chown -R 10001:10001 /app
USER 10001:10001
EXPOSE 8080
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/health',timeout=3)"
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["mwm-server"]
