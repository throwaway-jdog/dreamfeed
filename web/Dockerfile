FROM python:3.12-alpine
WORKDIR /app
COPY app.py index.html /app/
# Shared sign-in library (the formlogin build context, see docker-compose.yml).
COPY --from=formlogin formlogin /app/formlogin
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/app.py"]
