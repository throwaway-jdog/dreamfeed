FROM python:3.12-alpine
WORKDIR /app
# The live Feed reads X with gallery-dl (its metadata only: nothing is downloaded).
RUN pip install --no-cache-dir gallery-dl==1.32.19
COPY app.py dvr.py index.html /app/
COPY static /app/static
COPY vendor /app/vendor
# Shared sign-in library (the formlogin build context, see docker-compose.yml).
COPY --from=formlogin formlogin /app/formlogin
# From the worker (its build context): its persona and safety rules, so the persona editor
# checks edits exactly as the worker will (core), the live sites (feed) and Chaturbate's (live).
# Pure Python: only what these import is used (none of the worker's GPU code).
COPY --from=worker dreamfeed/__init__.py /app/dreamfeed/
COPY --from=worker dreamfeed/core /app/dreamfeed/core
COPY --from=worker dreamfeed/feed /app/dreamfeed/feed
COPY --from=worker dreamfeed/live /app/dreamfeed/live
ENV PYTHONUNBUFFERED=1 XDG_CACHE_HOME=/tmp
CMD ["python", "/app/app.py"]
