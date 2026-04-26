# Руководство по развертыванию сервера Meshtastic

Это руководство описывает, как развернуть компоненты сервера Meshtastic на Linux-сервере (пример для Ubuntu/Debian).

## Предварительные требования

1. Linux-сервер (Ubuntu 22.04 LTS или аналогичный)
2. Доступ root или sudo
3. MQTT брокер (мы будем использовать Mosquitto)
4. Python 3.8+
5. Git (для клонирования репозитория, если нужно)

## Шаг 1: Обновление системы и установка зависимостей

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv mosquitto mosquitto-clients
```

## Шаг 2: Получение кода сервера

Если у вас есть код локально (как в текущей директории), скопируйте его на сервер:
```bash
# Предположим, вы находитесь в директории с кодом на вашей локальной машине
scp -r . user@your_server_ip:/opt/meshtastic
```

Альтернативно, если код находится в Git-репозитории:
```bash
git clone https://github.com/BZ6/messanger-server.git /opt/meshtastic
```

## Шаг 3: Настройка виртуального окружения Python и установка зависимостей

```bash
sudo mkdir -p /opt/meshtastic
sudo chown $USER:$USER /opt/meshtastic
cd /opt/meshtastic
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

## Шаг 4: Настройка Mosquitto (MQTT брокера)

Конфигурация Mosquetti по умолчанию обычно достаточно для localhost. 
Если вам нужно разрешить удаленные подключения (чтобы устройства Meshtastic могли подключаться), отредактируйте `/etc/mosquitto/mosquitto.conf` и добавьте:

```
listener 1883
allow_anonymous true
```

Затем перезапустите Mosquitto:
```bash
sudo systemctl restart mosquitto
```

## Шаг 5: Создание отдельного системного пользователя (рекомендуется)

```bash
sudo useradd -r -s /usr/false meshtastic
sudo chown -R meshtastic:meshtastic /opt/meshtastic
```

## Шаг 6: Установка файлов системных сервисов

Скопируйте предоставленные файлы сервисов в директорию systemd:
```bash
sudo cp meshtastic-collector.service meshtastic-router.service /etc/systemd/system/
```

## Шаг 7: Перезагрузка systemd и запуск сервисов

```bash
sudo systemctl daemon-reload
sudo systemctl enable meshtastic-collector meshtastic-router
sudo systemctl start meshtastic-collector meshtastic-router
```

## Шаг 8: Проверка работы сервисов

```bash
sudo systemctl status meshtastic-collector
sudo systemctl status meshtastic-router
```

Вы должны увидеть "active (running)" для обоих.

## Шаг 9: Просмотр журналов для устранения неполадок

```bash
# Следить за логами коллектора
sudo journalctl -u meshtastic-collector -f

# В другом терминале следить за логами роутера
sudo journalctl -u meshtastic-router -f
```

## Шаг 10: Тестирование настройки (Опционально)

Вы можете использовать `mosquitto_sub` для проверки того, что коллектор правильно подписывается или публикует.
Например, чтобы увидеть информацию о узлах Meshtastic (если какие-то устройства подключены):
```bash
mosquitto_sub -h localhost -t "msh/+/2/json/#"
```

## Структура каталогов на сервере

```
/opt/meshtastic/
├── venv/                    # Виртуальное окружение Python
├── services/
│   ├── collector/
│   │   ├── collector.py
│   │   └── tests/
│   ├── recommendation_engine/
│   │   ├── router.py
│   │   └── tests/
│   ├── node_service/
│   │   ├── node_service.py
│   │   └── tests/
│   ├── shared/
│   │   └── db.py
│   └── graph_service/
│       ├── graph_api.py
│       └── tests/
├── meshtastic-collector.service
├── meshtastic-router.service
├── requirements.txt
└── serverctl.sh
```

## Управление сервисами с помощью serverctl.sh

Вы можете использовать предоставленный вспомогательный скрипт:
```bash
# Запустить все службы
./serverctl.sh start

# Остановить все службы
./serverctl.sh stop

# Перезапустить все службы
./serverctl.sh restart

# Проверить статус
./serverctl.sh status

# Просмотреть логи для службы (например, коллектора)
./serverctl.sh logs meshtastic-collector
```

## Примечания

1. Сервис коллектора записывает данные в базу SQLite по адресу `/var/lib/meshtastic/mesh_network.db` (значение по умолчанию из `services/shared/db.py`). 
   Убедитесь, что пользователь `meshtastic` имеет права записи в `/var/lib/meshtastic/`.
   При необходимости можно изменить путь к базе данных, установив переменную окружения `MESHTASTIC_DB` в файлах сервисов.

2. Сервис роутера не общается напрямую с MQTT; он читает данные из базы данных, заполненной коллектором.

3. Для production рекомендуется защитить ваш MQTT брокер (например, использовать пароли, TLS) и ограничить доступ.

## Устранение неполадок

- **Служба не запускается**: Проверьте журналы с помощью `journalctl -u <служба> -e`
- **Ошибки базы данных**: Убедитесь, что директория `/var/lib/meshtastic` существует и доступна для записи пользователю `meshtastic`.
- **Проблемы с подключением MQTT**: Проверьте, что брокер запущен и доступен (`sudo systemctl status mosquitto`), и посмотрите логи коллектора на сообщения о подключении.

## Опционально: Веб-интерфейс для визуализации графа

Если вы хотите развернуть опциональный веб-интерфейс (не входит в базовые требования), вам потребуется:
1. Установить веб-сервер (например, Nginx) для раздачи статических файлов.
2. Развернуть фронтенд, который будет запрашивать API графа (предоставляется `services.graph_service.graph_api`).
3. Это руководство не включает веб-интерфейс, так как он был отмечен как опциональный.

---

Ваш сервер Meshtastic теперь готов принимать данные от устройств Meshtastic через MQTT, хранить информацию об узлах и ребрах, а также предоставлять рекомендации по маршрутам.