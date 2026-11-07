FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt \
    && useradd --create-home --uid 10001 harbourline \
    && install -d -o harbourline -g harbourline /var/data/harbourline
COPY harbourline/ harbourline/
COPY modules/ modules/
COPY schemas/ schemas/
COPY scripts/ scripts/
COPY examples/request.json examples/request.json
USER harbourline
EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn --workers 1 --threads 4 --bind 0.0.0.0:${PORT:-8000} 'harbourline.web:create_app()'"]
