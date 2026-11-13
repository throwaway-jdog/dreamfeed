# The follow service (python -m dreamfeed follow): standard-library Python, and ffmpeg for your
# recordings' posters and highlights and Saved's copies of videos.
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY dreamfeed /app/dreamfeed
WORKDIR /app
ENV HOME=/tmp PYTHONUNBUFFERED=1
CMD ["python", "-m", "dreamfeed", "follow"]
