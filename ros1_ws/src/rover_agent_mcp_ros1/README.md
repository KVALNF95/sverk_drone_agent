# rover_agent_mcp_ros1

ROS 1 port of the rover text agent. It keeps the fleet `message_id` outside the LLM prompt and restores it in `/agent/status` and `/agent/answer`.

Motion/pose/scan use standard ROS 1 interfaces. `navigate_to_pose` uses `move_base`. LED tools become active when a ROS 1 `rover_interfaces` package with compatible message/service types is installed.
