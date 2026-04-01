FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn
COPY memory_bridge.py api.py ./
EXPOSE 18810
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "18810"]
