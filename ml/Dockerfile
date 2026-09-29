# The ML service. The vision dependencies (torch, ultralytics, rfdetr) are large and only
# needed for real inference, so they are installed separately and the default image runs in
# MOCK_INFERENCE mode. Uncomment the second pip layer to build a full inference image.
FROM python:3.13-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY ml/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# RUN pip install --no-cache-dir torch opencv-python ultralytics "rfdetr[plus]" supervision

COPY ml/ ./
# The demo results the mock path copies from, and the sample captures.
COPY web/public/results/ /app/demo-results/
COPY assets/ /app/assets/

ENV DEMO_RESULTS_DIR=/app/demo-results \
    PYTHONUNBUFFERED=1

RUN useradd -u 10001 -m toothfairy && chown -R toothfairy /app
USER toothfairy

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
