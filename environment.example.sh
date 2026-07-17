#!/usr/bin/env bash
# Example only. Copy the required values to ~/.bashrc on the drone.

# Fleet identity and server
export FLEET_ROBOT_ID='drone-01'
export FLEET_SERVER_IP='10.194.179.111'
export FLEET_MQTT_HOST="$FLEET_SERVER_IP"
export FLEET_MQTT_PORT='1883'
export FLEET_MQTT_TOPIC_PREFIX='fleet/v1/robots'
export FLEET_MQTT_USERNAME=''
export FLEET_MQTT_PASSWORD=''
export FLEET_AGENT_COMMAND_TIMEOUT_SEC='300'
export FLEET_DUPLICATE_CACHE_SIZE='100'

# ROS 1 network (example drone IP)
export ROS_MASTER_URI='http://127.0.0.1:11311'
export ROS_IP='10.194.179.171'
unset ROS_HOSTNAME

# Agent topics
export AGENT_TEXT_COMMAND_TOPIC='/agent/text_command'
export AGENT_STATUS_TOPIC='/agent/status'
export AGENT_ANSWER_TOPIC='/agent/answer'

# LLM
export OPENAI_BASE_URL='https://ai.sverk.io/v1'
export OPENAI_MODEL='qwen35'
export OPENAI_API_KEY='CHANGE_ME'
export LLM_API_KEY_ENV='OPENAI_API_KEY'
export LLM_NATIVE_TOOL_MODE='auto'
export LLM_TIMEOUT_SEC='120'
export LLM_MAX_TOOL_ROUNDS='8'
export LLM_APP_TITLE='sverk-drone-agent-01'

# Local MCP HTTP server
export MCP_HOST='127.0.0.1'
export MCP_PORT='8765'
export MCP_URL="http://$MCP_HOST:$MCP_PORT/mcp"

# SVERH/Clover service names
export DRONE_GET_TELEMETRY_SERVICE='get_telemetry'
export DRONE_NAVIGATE_SERVICE='navigate'
export DRONE_NAVIGATE_GLOBAL_SERVICE='navigate_global'
export DRONE_SET_ALTITUDE_SERVICE='set_altitude'
export DRONE_SET_YAW_SERVICE='set_yaw'
export DRONE_SET_POSITION_SERVICE='set_position'
export DRONE_LAND_SERVICE='land'
export DRONE_LED_EFFECT_SERVICE='/led/set_effect'

# Local safety envelope. Keep conservative values for initial supervised tests.
export DRONE_MAX_ALTITUDE_M='3.0'
export DRONE_MIN_FLIGHT_ALTITUDE_M='0.20'
export DRONE_MAX_SPEED_MPS='1.0'
export DRONE_MAX_HORIZONTAL_COORDINATE_M='6.0'
export DRONE_MAX_RELATIVE_DISTANCE_M='3.0'
export DRONE_MAX_RELATIVE_VERTICAL_M='1.5'
export DRONE_DEFAULT_TAKEOFF_HEIGHT_M='1.0'
export DRONE_DEFAULT_SPEED_MPS='0.5'
export DRONE_ARRIVAL_TOLERANCE_M='0.25'
export DRONE_NAVIGATION_TIMEOUT_SEC='60'
export DRONE_SERVICE_TIMEOUT_SEC='5'
export DRONE_REQUIRE_CONNECTED='1'
export DRONE_MIN_TAKEOFF_VOLTAGE_V='0'
export DRONE_ALLOWED_FRAMES='map,body,aruco_map,navigate_target,terrain'

# Flight commands are enabled only when explicitly requested by the operator.
export DRONE_ENABLE_FLIGHT_TOOLS='0'
export DRONE_ALLOW_LAND_WHEN_DISABLED='1'
export DRONE_LAND_ON_SEQUENCE_ERROR='0'

# Pseudo-agent (rule-based, no LLM)
export PSEUDO_TAKEOFF_HEIGHT_M='0.8'
export PSEUDO_MOVE_SPEED_MPS='0.5'
export PSEUDO_LAND_WAIT_UNTIL_DISARMED='0'
export CHESS_CELL_SIZE_M='0.4'
export CHESS_SIDE='white'
