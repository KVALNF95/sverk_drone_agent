#!/usr/bin/env python3
from pathlib import Path
import os
import threading
import traceback

import rospy
from std_msgs.msg import String

from drone_agent_mcp_ros1.fleet_protocol import (
    make_answer_payload,
    make_status_payload,
    parse_command_payload,
)
from drone_agent_mcp_ros1.mcp_client import McpJsonRpcClient
from drone_agent_mcp_ros1.openrouter_host import DEFAULT_SYSTEM_PROMPT, OpenRouterHost
from drone_agent_mcp_ros1.utils import json_dumps


class DroneAgentTextNodeRos1:
    """Text agent compatible with the rover agent's fleet envelope protocol."""

    def __init__(self):
        self.robot_id = os.getenv("FLEET_ROBOT_ID", "drone-01").strip()
        self.command_topic = os.getenv("AGENT_TEXT_COMMAND_TOPIC", "/agent/text_command")
        self.status_topic = os.getenv("AGENT_STATUS_TOPIC", "/agent/status")
        self.answer_topic = os.getenv("AGENT_ANSWER_TOPIC", "/agent/answer")
        self.mcp_url = os.getenv("MCP_URL", "http://127.0.0.1:%s/mcp" % os.getenv("MCP_PORT", "8765"))
        self.prompt_file = os.getenv("AGENT_PROMPT_FILE", "")
        self.timeout = float(os.getenv("LLM_TIMEOUT_SEC", "120"))
        self.max_rounds = int(os.getenv("LLM_MAX_TOOL_ROUNDS", "8"))
        self.active = False
        self.lock = threading.Lock()

        self.status_pub = rospy.Publisher(self.status_topic, String, queue_size=10)
        self.answer_pub = rospy.Publisher(self.answer_topic, String, queue_size=10)
        rospy.Subscriber(self.command_topic, String, self.on_command, queue_size=10)

        rospy.loginfo(
            "Drone agent %s listens on %s, publishes %s and %s",
            self.robot_id,
            self.command_topic,
            self.status_topic,
            self.answer_topic,
        )
        rospy.loginfo(
            "Fleet protocol: server message_id is excluded from the LLM prompt and restored in status/answer."
        )

    def publish(self, publisher, payload):
        publisher.publish(String(data=json_dumps(payload)))

    def system_prompt(self):
        if not self.prompt_file:
            return DEFAULT_SYSTEM_PROMPT
        path = Path(self.prompt_file).expanduser()
        if not path.is_file():
            rospy.logwarn("AGENT_PROMPT_FILE does not exist: %s", path)
            return DEFAULT_SYSTEM_PROMPT
        text = path.read_text(encoding="utf-8").strip()
        return DEFAULT_SYSTEM_PROMPT + "\n\n# Пользовательская кастомизация поведения\n" + text if text else DEFAULT_SYSTEM_PROMPT

    def create_host(self):
        key = ""
        names = (
            os.getenv("LLM_API_KEY_ENV", "OPENAI_API_KEY"),
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "SVERK_API_KEY",
        )
        for name in names:
            if name and os.getenv(name):
                key = os.getenv(name, "")
                break
        model = os.getenv("OPENAI_MODEL") or os.getenv("OPENROUTER_MODEL") or os.getenv("SVERK_MODEL", "")
        base = (
            os.getenv("OPENAI_BASE_URL")
            or os.getenv("OPENROUTER_BASE_URL")
            or os.getenv("SVERK_BASE_URL")
            or "https://openrouter.ai/api/v1"
        )
        return OpenRouterHost(
            api_key=key,
            model=model,
            base_url=base,
            timeout_s=self.timeout,
            max_tool_rounds=self.max_rounds,
            http_referer=os.getenv("OPENROUTER_HTTP_REFERER", ""),
            app_title=os.getenv("LLM_APP_TITLE", "sverk-drone-agent-ros1"),
            system_prompt=self.system_prompt(),
            native_tool_mode=os.getenv("LLM_NATIVE_TOOL_MODE", "auto"),
        )

    def on_command(self, msg):
        try:
            context = parse_command_payload(msg.data, self.robot_id)
        except ValueError as exc:
            rospy.logwarn("Invalid command: %s", exc)
            return

        with self.lock:
            if self.active:
                text = "Агент всё ещё выполняет предыдущую команду."
                self.publish(self.status_pub, make_status_payload(context, status="error", text=text))
                self.publish(self.answer_pub, make_answer_payload(context, status="error", text=text))
                return
            self.active = True

        rospy.loginfo("Received agent command %s: %s", context.message_id, context.text)
        threading.Thread(target=self.run, args=(context,), daemon=True).start()

    def run(self, context):
        try:
            self.publish(
                self.status_pub,
                make_status_payload(context, status="running", text="Команда получена локальным агентом."),
            )
            result = self.create_host().run_command(
                context.text,
                McpJsonRpcClient(self.mcp_url, timeout_s=self.timeout),
            )
            rospy.loginfo("Agent result: %s", json_dumps(result))
            reply = str(result.get("reply") or "Готово.").strip()
            status = "completed" if bool(result.get("success", True)) else "error"
            self.publish(self.answer_pub, make_answer_payload(context, status=status, text=reply))
        except Exception as exc:
            rospy.logerr("Agent failed: %s\n%s", exc, traceback.format_exc())
            text = "Ошибка агента: %s" % exc
            self.publish(self.status_pub, make_status_payload(context, status="error", text=text))
            self.publish(self.answer_pub, make_answer_payload(context, status="error", text=text))
        finally:
            with self.lock:
                self.active = False


def main():
    rospy.init_node("drone_agent_text_node")
    DroneAgentTextNodeRos1()
    rospy.spin()


if __name__ == "__main__":
    main()
