FROM python:3.14-alpine
WORKDIR /app
COPY dao-v1.0/requirements.txt ./dao-v1.0/requirements.txt
RUN pip install --no-cache-dir -r dao-v1.0/requirements.txt
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]
