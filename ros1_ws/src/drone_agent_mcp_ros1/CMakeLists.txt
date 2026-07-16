cmake_minimum_required(VERSION 3.0.2)
project(drone_agent_mcp_ros1)

find_package(catkin REQUIRED COMPONENTS rospy std_msgs std_srvs)
catkin_python_setup()
catkin_package(CATKIN_DEPENDS rospy std_msgs std_srvs)

catkin_install_python(
  PROGRAMS
    scripts/agent_text_node.py
    scripts/drone_mcp_server.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch config DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION})
