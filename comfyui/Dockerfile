# ComfyUI (plus the GGUF loader node), started and stopped on demand by supervisor.py so it only holds the GPU while
# the worker is generating (the miner yields to any GPU user).
FROM pytorch/pytorch:2.14.1-cuda13.0-cudnn9-runtime
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
ARG COMFYUI_VERSION=v0.41.0
RUN git clone --depth 1 --branch ${COMFYUI_VERSION} https://github.com/comfyanonymous/ComfyUI.git /app/ComfyUI
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN pip install --no-cache-dir -r /app/ComfyUI/requirements.txt
# GGUF loader, for the compressed Wan 2.2 video model that fits in 12 GB.
ARG COMFYUI_GGUF_COMMIT=6ea2651e7df66d7585f6ffee804b20e92fb38b8a
RUN git clone https://github.com/city96/ComfyUI-GGUF.git /app/ComfyUI/custom_nodes/ComfyUI-GGUF \
    && git -C /app/ComfyUI/custom_nodes/ComfyUI-GGUF checkout ${COMFYUI_GGUF_COMMIT} \
    && pip install --no-cache-dir -r /app/ComfyUI/custom_nodes/ComfyUI-GGUF/requirements.txt
# SageAttention: a faster attention kernel (triton, no compiling), used for video jobs.
RUN pip install --no-cache-dir sageattention==1.0.6
COPY extra_model_paths.yaml supervisor.py /app/
WORKDIR /app
ENV HOME=/tmp PYTHONUNBUFFERED=1
CMD ["python", "supervisor.py"]
