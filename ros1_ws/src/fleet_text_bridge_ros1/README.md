# fleet_text_bridge_ros1

Transport-only ROS 1 package for the SVERH AI Agents server.

It reads all runtime settings from environment variables, subscribes to the robot-specific MQTT command topic, publishes the received envelope to `/agent/text_command`, and forwards `/agent/status` and `/agent/answer` to MQTT.

Required variables:

```bash
export FLEET_ROBOT_ID='drone-01'
export FLEET_MQTT_HOST='10.194.179.111'
export FLEET_MQTT_PORT='1883'
```

Launch:

```bash
roslaunch fleet_text_bridge_ros1 bridge.launch
```
