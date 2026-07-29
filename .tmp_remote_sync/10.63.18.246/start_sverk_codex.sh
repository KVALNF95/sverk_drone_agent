#!/usr/bin/env bash
source /opt/ros/noetic/setup.bash
source /home/pi/catkin_ws/devel/setup.bash
export ROS_HOSTNAME="$(hostname).local"
exec stdbuf -o L roslaunch sverk sverk.launch --wait --screen --skip-log-check
