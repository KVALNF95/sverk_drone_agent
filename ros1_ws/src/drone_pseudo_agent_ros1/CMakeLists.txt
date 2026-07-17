cmake_minimum_required(VERSION 3.0.2)
project(drone_pseudo_agent_ros1)

find_package(catkin REQUIRED COMPONENTS drone_agent_mcp_ros1 rospy std_msgs)
catkin_python_setup()
catkin_package(CATKIN_DEPENDS drone_agent_mcp_ros1 rospy std_msgs)

catkin_install_python(
  PROGRAMS
    scripts/pseudo_agent_text_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION})
