# kohya musubi-tuner for Wan 2.2 I2V video LoRAs (it needs a newer torch than ../trainer).
FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime
RUN apt-get update && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*
# v0.3.6
ARG MUSUBI_REF=f8a1b03794a49239a3539015075f5123d6c07d66
RUN git clone https://github.com/kohya-ss/musubi-tuner.git /musubi \
    && cd /musubi && git checkout ${MUSUBI_REF} && pip install --no-cache-dir -e .
WORKDIR /musubi
ENV HOME=/tmp PYTHONUNBUFFERED=1
COPY train.sh /train.sh
ENTRYPOINT ["sh", "/train.sh"]
