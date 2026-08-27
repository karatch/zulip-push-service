FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir zulip==0.9.1 requests

COPY zulip_listener.py .

CMD ["python", "-u", "zulip_listener.py"]
