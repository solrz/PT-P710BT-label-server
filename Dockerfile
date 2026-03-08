FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends fonts-noto-cjk && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask packbits Pillow

WORKDIR /app
COPY app.py /app/

EXPOSE 9100
CMD ["python3", "app.py"]
