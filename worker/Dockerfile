# CUDA 13.0 build: the newest the host driver (580) supports.
FROM pytorch/pytorch:2.14.1-cuda13.0-cudnn9-runtime
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/
# Single-purpose image: install alongside the bundled torch instead of in a venv.
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY dreamfeed /app/dreamfeed
WORKDIR /app
ENV HOME=/tmp PYTHONUNBUFFERED=1
CMD ["python", "-m", "dreamfeed", "run"]
