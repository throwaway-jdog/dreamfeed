# ComfyUI, started and stopped on demand by supervisor.py so it only holds the GPU while
# the worker is generating (the miner yields to any GPU user).
FROM pytorch/pytorch:2.14.1-cuda13.0-cudnn9-runtime
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
ARG COMFYUI_VERSION=v0.41.0
RUN git clone --depth 1 --branch ${COMFYUI_VERSION} https://github.com/comfyanonymous/ComfyUI.git /app/ComfyUI
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN pip install --no-cache-dir -r /app/ComfyUI/requirements.txt
COPY extra_model_paths.yaml supervisor.py /app/
WORKDIR /app
ENV HOME=/tmp PYTHONUNBUFFERED=1
CMD ["python", "supervisor.py"]
