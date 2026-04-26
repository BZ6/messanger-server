#!/bin/bash
# serverctl.sh – запуск/остановка сервисов Meshtastic

SERVICES=("mosquitto" "meshtastic-collector" "meshtastic-router")

start() {
    for s in "${SERVICES[@]}"; do
        sudo systemctl start "$s"
        echo "✔ $s started"
    done
}

stop() {
    for s in "${SERVICES[@]}"; do
        sudo systemctl stop "$s"
        echo "✘ $s stopped"
    done
}

restart() {
    for s in "${SERVICES[@]}"; do
        sudo systemctl restart "$s"
        echo "⟳ $s restarted"
    done
}

status() {
    for s in "${SERVICES[@]}"; do
        active=$(systemctl is-active "$s")
        if [ "$active" = "active" ]; then
            echo "✅ $s: $active"
        else
            echo "❌ $s: $active"
        fi
    done
}

logs() {
    sudo journalctl -u "$2" -f
}

case "$1" in
    start) start ;;
    stop) stop ;;
    restart) restart ;;
    status) status ;;
    logs) logs "$@" ;;
    *) echo "Usage: $0 {start|stop|restart|status|logs <service>}" ;;
esac