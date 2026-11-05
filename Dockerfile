FROM python:3.12-slim

LABEL org.opencontainers.image.title="SUYA" \
      org.opencontainers.image.description="Collects Antarctic ocean temperature, salinity and air temperature from public APIs into SQLite and monthly Excel workbooks, without a window" \
      org.opencontainers.image.source="https://github.com/jongsu-king/SUYA" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /src
COPY pyproject.toml README.md ./
COPY antarctic_monitor ./antarctic_monitor
RUN pip install --no-cache-dir . && rm -rf /src

ENV XDG_DATA_HOME=/data \
    MONITOR_DB_PATH=/data/SUYA/antarctic.db \
    MONITOR_EXCEL_DIR=/data/SUYA/excel \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
WORKDIR /data

CMD ["suya", "daemon"]
