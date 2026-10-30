FROM python:3.12-slim

# Languages to install (Tesseract "best" models). Add more codes here: hin mal tel kan san ben ...
ARG LANGS="tam eng"

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr curl \
 && rm -rf /var/lib/apt/lists/*

# Put the high-accuracy models next to Tesseract's own configs + pdf.ttf (needed for searchable PDF)
RUN TD=$(dirname $(find /usr/share/tesseract-ocr -name osd.traineddata | head -1)) \
 && ln -s "$TD" /tessdata \
 && for l in $LANGS; do \
      curl -fsSL -o "$TD/$l.traineddata" "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/$l.traineddata"; \
    done

WORKDIR /app
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend frontend

ENV TESSDATA_PREFIX=/tessdata DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
WORKDIR /app/backend
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
