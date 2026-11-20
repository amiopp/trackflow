FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY trackflow/ trackflow/
COPY sql/ sql/
COPY pipelines.yaml .

# Build the warehouse at start-up, then serve the dashboard
CMD ["sh", "-c", "python -m trackflow.cli generate && python -m trackflow.cli run && python -m trackflow.cli serve --host 0.0.0.0"]
EXPOSE 5000
