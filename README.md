# SVERH Clover Drone Agent ROS 1 — v1.0.0

Архив содержит **три ROS 1 пакета**:

1. `fleet_text_bridge_ros1` — подключение к серверу СВЕРХ AI Agents по MQTT;
2. `drone_agent_mcp_ros1` — текстовый LLM-агент и MCP-сервер с высокоуровневыми инструментами SVERH/Clover.
3. `drone_pseudo_agent_ros1` — rule-based pseudo-agent без LLM для простых относительных и шахматных команд.

## Архитектура

```text
SVERH AI Agents server
        │ MQTT: fleet/v1/robots/<robot_id>/command
        ▼
fleet_text_bridge_ros1
        │ /agent/text_command (std_msgs/String JSON)
        ▼
drone_agent_text_node
        │ local HTTP JSON-RPC MCP
        ▼
drone_mcp_server
        │ ROS 1 services
        ▼
SVERH/Clover simple_offboard + LED
```

Ответ проходит обратно через `/agent/status` и `/agent/answer`, затем bridge публикует его в MQTT. Агент передаёт в LLM только поле `text`; серверные `message_id` и `robot_id` сохраняются вне промпта и возвращаются в ответном envelope.

## Поддерживаемые MCP tools

Информационные и общие:

- `get_available_tools`
- `wait`
- `drone_get_telemetry`
- `drone_get_system_status`
- `drone_set_led_effect`

Полётные высокоуровневые инструменты:

- `drone_takeoff`
- `drone_land`
- `drone_navigate`
- `drone_navigate_to_chess_cell`
- `drone_move_relative`
- `drone_set_altitude`
- `drone_set_yaw`
- `drone_hold_position`
- `drone_wait_until_arrival`
- `drone_run_sequence`

Низкоуровневые `set_attitude`, `set_rates`, прямой MAVROS, shell и disarm намеренно отсутствуют.

## Обязательный safety interlock

Физические полётные команды **заблокированы по умолчанию**. Для них нужен:

- административный запрос `DRONE_ENABLE_FLIGHT_TOOLS=1`.

`drone_land` и `drone_hold_position` остаются доступными как защитные действия. Если нужен автоматический уход на посадку после ошибки в уже начатой последовательности, можно включить `DRONE_LAND_ON_SEQUENCE_ERROR=1`; по умолчанию агент выполняет `hold`.

Проверку коммуникации, LLM, телеметрии, LED и списка MCP tools можно выполнить без разрешения на полёт.

## 1. Установка

Распакуйте архив в домашнюю директорию дрона:

```bash
unzip sverk-clover-drone-ros1-v1.0.0.zip
cd sverk-clover-drone-ros1-v1.0.0/ros1_ws
```

Установите зависимости:

```bash
sudo apt update
sudo apt install -y python3-paho-mqtt python3-catkin-tools
```

На образе дрона уже должны присутствовать ROS 1 и пакет сервисов `sverk` либо `clover`.

Соберите workspace:

```bash
source /opt/ros/noetic/setup.bash
catkin_make
source devel/setup.bash
```

## 2. Переменные окружения

Скопируйте шаблон и внесите реальные значения:

```bash
cp ../environment.example.sh ~/.sverk_drone_agent_env.sh
nano ~/.sverk_drone_agent_env.sh
```

Подключите его в `~/.bashrc`:

```bash
echo 'source ~/.sverk_drone_agent_env.sh' >> ~/.bashrc
source ~/.bashrc
```

Минимально необходимы:

```bash
export FLEET_ROBOT_ID='drone-01'
export FLEET_SERVER_IP='10.194.179.111'
export FLEET_MQTT_HOST="$FLEET_SERVER_IP"
export FLEET_MQTT_PORT='1883'
export ROS_MASTER_URI='http://127.0.0.1:11311'
export ROS_IP='10.194.179.171'  # пример IP дрона
export OPENAI_BASE_URL='https://ai.sverk.io/v1'
export OPENAI_MODEL='qwen35'
export OPENAI_API_KEY='...'
```

IP и ID не хранятся в YAML пакетов.

Для шахматного полёта и более точной посадки в клетку можно отдельно настроить:

```bash
export CHESS_TAKEOFF_SPEED_MPS='0.3'
export CHESS_ALIGNMENT_HOLD_SEC='3.5'
export CHESS_ALIGNMENT_SPEED_MPS='0.2'
export CHESS_ALIGNMENT_TOLERANCE_M='0.10'
export CHESS_FINAL_APPROACH_ALTITUDE_M='0.4'
export CHESS_LANDING_SPEED_MPS='0.2'
export CHESS_LAND_WAIT_UNTIL_DISARMED='0'
```

## 3. Проверка сети

```bash
ping -c 3 "$FLEET_SERVER_IP"
curl "http://$FLEET_SERVER_IP:8080/health"
nc -vz "$FLEET_MQTT_HOST" "$FLEET_MQTT_PORT"
```

## 4. Запуск

Убедитесь, что основная система Clover/SVERH и локальный ROS master запущены.

Одной командой:

```bash
source /opt/ros/noetic/setup.bash
source ~/sverk-clover-drone-ros1-v1.0.0/ros1_ws/devel/setup.bash
roslaunch fleet_text_bridge_ros1 drone_agent_stack.launch
```

Для pseudo-agent без LLM:

```bash
roslaunch fleet_text_bridge_ros1 drone_pseudo_agent_stack.launch
```

Либо отдельно:

```bash
roslaunch fleet_text_bridge_ros1 bridge.launch
```

```bash
roslaunch drone_agent_mcp_ros1 agent_mcp.launch
```

```bash
roslaunch drone_pseudo_agent_ros1 pseudo_agent.launch
```

Не запускайте второй экземпляр MCP на том же `MCP_PORT`.

## 5. Проверка без полёта

ROS-узлы:

```bash
rosnode list | grep -E 'fleet_text_bridge|drone_agent|drone_mcp'
```

Топики:

```bash
rostopic list | grep '^/agent/'
```

MCP health:

```bash
curl -sS "http://127.0.0.1:$MCP_PORT/health" | python3 -m json.tool
```

Список tools:

```bash
curl -sS -X POST "http://127.0.0.1:$MCP_PORT/mcp" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | python3 -m json.tool
```

Телеметрия через MCP:

```bash
curl -sS -X POST "http://127.0.0.1:$MCP_PORT/mcp" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"drone_get_telemetry","arguments":{"frame_id":"map"}}}' \
  | python3 -m json.tool
```

Проверка текстового агента локально без серверного ID:

```bash
rostopic pub -1 /agent/text_command std_msgs/String \
  "data: 'Сообщи телеметрию и готовность систем. Не выполняй полёт.'"
```

Смотрите ответ:

```bash
rostopic echo /agent/answer
```

## 6. Проверка через сервер и web-чат

На сервере проверьте online-состояние:

```bash
curl "http://127.0.0.1:8080/api/v1/robots/$FLEET_ROBOT_ID" | python3 -m json.tool
```

Откройте:

```text
http://<IP_СЕРВЕРА>:8080/chat
```

Безопасный тест сообщения:

```text
@drone_01 Сообщи текущую телеметрию и список доступных возможностей. Не выполняй полёт.
```

## 7. Диагностика

MQTT на сервере:

```bash
docker exec -it robot-mosquitto \
  mosquitto_sub -t 'fleet/v1/robots/#' -v
```

Сервисы на дроне:

```bash
rosservice list | grep -E 'get_telemetry|navigate|set_altitude|set_yaw|set_position|land|led/set_effect'
```

Если импорт `sverk.srv` недоступен, пакет автоматически пробует `clover.srv`.

## Источники API

Пакет реализован по документации SVERH `simple_offboard` и LED API, а также совместимым определениям сервисов Clover. Важное поведение: `navigate` возвращает управление сразу, поэтому ожидание реализовано через `get_telemetry(frame_id='navigate_target')` и проверку расстояния до цели.
