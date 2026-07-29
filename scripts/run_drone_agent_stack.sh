#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CATKIN_WS="${CATKIN_WS:-$(cd "$REPO_ROOT/../.." && pwd)}"
ENV_FILE="${SVERK_DRONE_AGENT_ENV_FILE:-$HOME/.sverk_drone_agent_env.sh}"
AGENT_MODE="${DRONE_AGENT_MODE:-agent}"

source /opt/ros/noetic/setup.bash
source "$CATKIN_WS/devel/setup.bash"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Environment file not found: $ENV_FILE" >&2
  exit 78
fi
source "$ENV_FILE"

# Hostname-based ROS addressing keeps autostart working after DHCP changes.
export ROS_MASTER_URI="${ROS_MASTER_URI:-http://127.0.0.1:11311}"
unset ROS_IP
export ROS_HOSTNAME="${ROS_HOSTNAME:-$(hostname).local}"

case "$AGENT_MODE" in
  agent)
    API_KEY_ENV="${LLM_API_KEY_ENV:-OPENAI_API_KEY}"
    if [[ -z "${!API_KEY_ENV:-}" ]]; then
      echo "$API_KEY_ENV is required for DRONE_AGENT_MODE=agent" >&2
      exit 78
    fi
    LAUNCH_FILE="drone_agent_stack.launch"
    ;;
  pseudo)
    LAUNCH_FILE="drone_pseudo_agent_stack.launch"
    ;;
  *)
    echo "DRONE_AGENT_MODE must be agent or pseudo, got: $AGENT_MODE" >&2
    exit 64
    ;;
esac

exec roslaunch --wait --screen fleet_text_bridge_ros1 "$LAUNCH_FILE"
