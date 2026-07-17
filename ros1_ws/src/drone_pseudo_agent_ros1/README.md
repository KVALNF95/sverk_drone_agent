# drone_pseudo_agent_ros1

Rule-based ROS 1 pseudo-agent for the SVERH/Clover drone.

It uses the same fleet text protocol as the LLM agent:

- input: `/agent/text_command`
- status: `/agent/status`
- answer: `/agent/answer`

Supported command families:

- initialize the current chess cell: `я в клетке e2`
- chess flight: `прилети из клетки e2 в клетку e4`
- relative flight: `прилети на 5 метров влево и 3 вперед`
- direct actions: `взлети`, `сядь`, `зависни`, `телеметрия`, `статус`

The pseudo-agent keeps the current chess cell only in memory. After restart it must be initialized again.
