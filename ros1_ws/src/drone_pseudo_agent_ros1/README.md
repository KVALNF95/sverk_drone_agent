# drone_pseudo_agent_ros1

Rule-based ROS 1 pseudo-agent for the SVERH/Clover drone.

It uses the same fleet text protocol as the LLM agent:

- input: `/agent/text_command`
- status: `/agent/status`
- answer: `/agent/answer`

Supported command families:

- initialize the current chess cell: `я в клетке e2`
- absolute chess flight by ArUco map: `прилети в клетку e4`
- chess flight: `прилети из клетки e2 в клетку e4`
- relative flight: `прилети на 5 метров влево и 3 вперед`
- direct actions: `взлети`, `сядь`, `зависни`, `телеметрия`, `статус`

Chess flights use absolute `aruco_map` coordinates of the chess field and move along the board axes one by one. The pseudo-agent still keeps the current chess cell in memory for operator context; after restart it can be initialized again with `я в клетке e2`.
