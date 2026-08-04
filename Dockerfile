# MCP Multi-Database Connector Docker Image - Multi-stage build

# Base stage with common dependencies
FROM python:3.11-slim AS base

# Set working directory
WORKDIR /app

# Install system dependencies for both SQL Server and PostgreSQL
RUN apt-get update && apt-get install -y \
    curl \
    apt-transport-https \
    gnupg2 \
    lsb-release \
    unixodbc \
    unixodbc-dev \
    libpq-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Optional legacy TLS support (opt-in, default off).
# Old database servers that only speak TLS 1.0/1.1 (e.g. SQL Server 2008/2012)
# fail the handshake against OpenSSL 3's TLS 1.2+ default with
# "SSL routines::unsupported protocol". Enable per module via:
#   docker-compose build args: ENABLE_LEGACY_TLS=true
# This lowers the container-wide TLS floor, so it must never be the default.
ARG ENABLE_LEGACY_TLS=false
RUN if [ "$ENABLE_LEGACY_TLS" = "true" ]; then \
        printf '%s\n' \
            'openssl_conf = openssl_init' \
            '' \
            '[openssl_init]' \
            'ssl_conf = ssl_sect' \
            '' \
            '[ssl_sect]' \
            'system_default = system_default_sect' \
            '' \
            '[system_default_sect]' \
            'MinProtocol = TLSv1' \
            'CipherString = DEFAULT@SECLEVEL=0' \
            > /etc/ssl/openssl-mcp.cnf; \
    else \
        cp /etc/ssl/openssl.cnf /etc/ssl/openssl-mcp.cnf; \
    fi
ENV OPENSSL_CONF=/etc/ssl/openssl-mcp.cnf

# Install Microsoft ODBC Driver 18 for SQL Server
RUN mkdir -p /usr/share/keyrings \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && chmod 644 /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64,armhf signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/11/prod bullseye main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 || \
    (echo "ODBC driver installation failed, using alternative approach" && \
    apt-get install -y freetds-dev && \
    echo "Using FreeTDS as ODBC alternative") \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files and source code
COPY pyproject.toml README.md constraints.txt ./
COPY src/ ./src/

# Install Python dependencies from pyproject.toml
# constraints.txt pins every transitive dependency version so a rebuild resolves the
# same tree. The version ranges in pyproject.toml still allow drift inside their bounds
# (an earlier rebuild moved mcp 1.28.1 -> 1.29.0 with no code change), which is exactly
# how an unnoticed upgrade reaches production. Regenerate with `pip freeze` inside a
# built image when dependencies change intentionally.
RUN pip install --no-cache-dir setuptools wheel && \
    pip install --no-cache-dir -c constraints.txt .

# Development stage
FROM base AS development

# Install development tools
RUN apt-get update && apt-get install -y \
    git \
    vim \
    nano \
    htop \
    && rm -rf /var/lib/apt/lists/*

# Install development Python packages
RUN pip install --no-cache-dir \
    pytest \
    pytest-asyncio \
    pytest-cov \
    black \
    flake8 \
    mypy \
    streamlit \
    pandas

# Copy source code (will be overridden by volume mount in dev)
COPY src/ ./src/

# Install package in development mode
RUN pip install --no-cache-dir -c constraints.txt -e .

# Create directories for logs and tests
RUN mkdir -p /app/logs /app/tests

# Set development environment variables
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MCP_DEBUG=1

# Expose ports for HTTP server and Streamlit
EXPOSE 8000 8501

# Default command for development (MCP server)
CMD ["python", "-m", "server"]

# Production stage
FROM base AS production

# Copy source code
COPY src/ ./src/

# Install package
RUN pip install --no-cache-dir -c constraints.txt -e .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash mcpuser && \
    mkdir -p /app/logs && \
    chown -R mcpuser:mcpuser /app

USER mcpuser

# Set production environment variables
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

# No image-level HEALTHCHECK: the same image runs in stdio mode (python -m server)
# and HTTP mode (python -m http_server), and only the latter has an endpoint to
# probe. Define the healthcheck per service in docker-compose instead.

# Default command for production
CMD ["python", "-m", "server"]