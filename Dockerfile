# Container image for hosted MCP deployments (referenced by smithery.yaml).
# Runs the stdio MCP server straight from the published PyPI package
# (floating version: deployments always get the latest release).
FROM python:3.12-slim

RUN pip install --no-cache-dir "photo-s-tools[mcp]"

ENTRYPOINT ["photo-s", "mcp"]
