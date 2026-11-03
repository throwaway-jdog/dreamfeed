# kohya sd-scripts for style LoRAs. v0.9.1 pins bitsandbytes 0.44 etc., which need torch 2.4 / CUDA 12.x
# (the host's 580 driver runs CUDA 12 images fine).
FROM pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime
RUN apt-get update && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
ARG SD_SCRIPTS_REF=8f4ee8fc343b047965cd8976fca65c3a35b7593a
# v0.9.1
RUN git clone https://github.com/kohya-ss/sd-scripts.git /sd-scripts \
    && cd /sd-scripts && git checkout ${SD_SCRIPTS_REF} \
    && pip install --no-cache-dir -r requirements.txt "numpy<2"
COPY train.sh /train.sh
WORKDIR /sd-scripts
ENV HOME=/tmp PYTHONUNBUFFERED=1
ENTRYPOINT ["bash", "/train.sh"]
