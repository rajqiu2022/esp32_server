FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libopus0 libsndfile1 gcc g++ ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY vendor/xiaozhi/main/xiaozhi-server/requirements.txt /tmp/voice-requirements.txt
RUN pip install --no-cache-dir torch==2.2.2 torchaudio==2.2.2 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /tmp/voice-requirements.txt
COPY requirements.txt /tmp/control-requirements.txt
RUN pip install --no-cache-dir -r /tmp/control-requirements.txt
COPY server/ server/
COPY scripts/ scripts/
COPY web/ web/
COPY vendor/xiaozhi/main/xiaozhi-server/ vendor/xiaozhi/main/xiaozhi-server/
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 ESP_BIND_HOST=0.0.0.0 ESP_DATA_DIR=/app/data
EXPOSE 8000 8002
CMD ["python", "scripts/run_all.py"]
