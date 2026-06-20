FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Node runtime alongside Python dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends nodejs npm && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Install Node dependencies
COPY package.json package-lock.json /app/
RUN npm ci --omit=dev

# Prepare project sources for editable install
COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
COPY node /app/node
COPY entrypoint.sh /app/entrypoint.sh

# Build React admin UI into src/admin/static
COPY admin-ui/package.json admin-ui/tsconfig.json admin-ui/vite.config.ts admin-ui/index.html /app/admin-ui/
COPY admin-ui/src /app/admin-ui/src
RUN cd /app/admin-ui && npm install && npm run build

RUN pip install --no-cache-dir -e .

RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 4000
