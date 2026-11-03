FROM python:3.12-slim-bookworm
# X changes often and breaks scrapers; bump this when sync starts failing.
ARG GALLERY_DL_VERSION=1.32.19
RUN pip install --no-cache-dir gallery-dl==${GALLERY_DL_VERSION}
COPY gallery-dl.conf run.py /app/
ENV HOME=/tmp PYTHONUNBUFFERED=1
CMD ["python", "/app/run.py"]
