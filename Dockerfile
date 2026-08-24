# Container image for hosted MCP deployments (referenced by smithery.yaml).
# Runs the stdio MCP server straight from the published PyPI package.
# Default is the latest release; pin for reproducible deployments:
#   docker build --build-arg PHOTO_S_VERSION=1.9.0 .
FROM python:3.12-slim

ARG PHOTO_S_VERSION
RUN if [ -n "$PHOTO_S_VERSION" ]; then \
        pip install --no-cache-dir "photo-s-tools[mcp]==$PHOTO_S_VERSION"; \
    else \
        pip install --no-cache-dir "photo-s-tools[mcp]"; \
    fi

ENTRYPOINT ["photo-s", "mcp"]
