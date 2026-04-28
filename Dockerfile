FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /var/lib/meshtastic

ENV MESHTASTIC_DB=/var/lib/meshtastic/mesh_network.db
ENV MQTT_BROKER=mosquitto
ENV MQTT_PORT=1883
ENV GRAPH_REFRESH_INTERVAL=30

# docker-compose overrides CMD per service; default shows help
CMD ["python", "-c", "print('Set command in docker-compose: collector | graph | router')"]
