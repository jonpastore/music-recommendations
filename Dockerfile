FROM python:3.12-slim
ARG VERSION=0.4.1
LABEL org.opencontainers.image.title="TIDAL Playlist Bridge" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.source="https://github.com/jonpastore/music-recommendations"
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV CONFIG_DIR=/config
ENV APP_VERSION=$VERSION
EXPOSE 8090
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
