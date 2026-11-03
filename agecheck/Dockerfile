# MiVOLO v2 age estimation on the CPU. Separate image because MiVOLO needs older torch and
# timm than the worker's tagger, and CPU so it never holds the GPU (the miner yields to any
# GPU user).
FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 \
        --index-url https://download.pytorch.org/whl/cpu
ARG MIVOLO_COMMIT=37475e3f8818b5f22448003feec3e64b01bfb188
RUN pip install --no-cache-dir \
        ultralytics==8.1.0 timm==0.8.13.dev0 transformers==4.51.0 accelerate==1.8.1 \
        omegaconf "lapx>=0.5.2" "numpy<2" \
        "git+https://github.com/WildChlamydia/MiVOLO.git@${MIVOLO_COMMIT}"
COPY server.py /app/
WORKDIR /app
ENV HOME=/tmp PYTHONUNBUFFERED=1 YOLO_CONFIG_DIR=/tmp
CMD ["python", "server.py"]
