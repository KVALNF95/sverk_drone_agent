# drone_agent_mcp_ros1

Локальный ROS 1 агент для дрона на прошивке СВЕРХ/Clover.

Пакет сохраняет тот же протокол, что агент ROS 2 ровера:

- вход: `/agent/text_command`, `std_msgs/String`;
- промежуточный статус: `/agent/status`;
- итоговый ответ: `/agent/answer`;
- серверные `message_id` и `robot_id` не передаются в LLM, но автоматически возвращаются в ответе.

## MCP tools

- `drone_get_telemetry`
- `drone_get_system_status`
- `drone_takeoff`
- `drone_land`
- `drone_navigate`
- `drone_move_relative`
- `drone_set_altitude`
- `drone_set_yaw`
- `drone_hold_position`
- `drone_wait_until_arrival`
- `drone_set_led_effect`
- `drone_run_sequence`
- `get_available_tools`
- `wait`

Инструменты используют высокоуровневые сервисы `simple_offboard`: `get_telemetry`, `navigate`, `set_altitude`, `set_yaw`, `set_position`, `land`, а также `/led/set_effect`.

## Встроенные ограничения

Полётные инструменты по умолчанию заблокированы (`DRONE_ENABLE_FLIGHT_TOOLS=0`). Это позволяет безопасно проверить MQTT, LLM, телеметрию и MCP без запуска движения.

При ошибке внутри `drone_run_sequence` агент по умолчанию выполняет `drone_hold_position`. Для автоматической посадки после уже выполненного взлёта можно включить `DRONE_LAND_ON_SEQUENCE_ERROR=1`.

Перед реальным запуском сначала проверьте дрон без пропеллеров либо в симуляторе, затем в закрытой контролируемой зоне с готовым ручным перехватом. Низкоуровневые `set_attitude`, `set_rates`, disarm, MAVROS и shell tools намеренно не предоставляются.

Официальные основы API:

- SVERH OFFBOARD: https://docs.sverh.tech/ru/commands_offboard_flight.html
- SVERH LED: https://docs.sverh.tech/ru/leds.html
