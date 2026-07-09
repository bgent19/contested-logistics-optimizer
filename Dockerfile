FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
COPY data ./data
COPY tests ./tests

RUN pip install --no-cache-dir -e ".[api,dev]"

ENV CLOPT_DATA=data/theater_sample.json
EXPOSE 8000

# Default: run the test suite so a fresh build self-verifies, then serve the API.
# Override the command to run the CLI instead, e.g.:
#   docker run --rm clopt:latest clopt allocate --data data/theater_sample.json
CMD ["sh", "-c", "pytest -q && uvicorn clopt.api:app --host 0.0.0.0 --port 8000"]
