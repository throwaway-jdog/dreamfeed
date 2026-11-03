FROM python:3.12-alpine
WORKDIR /app
COPY app.py index.html /app/
# Shared sign-in library (the formlogin build context, see docker-compose.yml).
COPY --from=formlogin formlogin /app/formlogin
# The worker's persona and safety rules, so the persona editor checks edits exactly as the
# worker will (the worker build context). Pure Python, no other worker code.
COPY --from=worker dreamfeed/personas.py dreamfeed/safety.py /app/dreamfeed/
RUN touch /app/dreamfeed/__init__.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/app.py"]
