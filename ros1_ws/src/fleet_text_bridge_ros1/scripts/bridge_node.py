#!/usr/bin/env python3
from collections import deque
import json
import os
import queue
import threading
import time

import paho.mqtt.client as mqtt
import rospy
from std_msgs.msg import String

from fleet_text_bridge_ros1.duplicate_cache import DuplicateCache
from fleet_text_bridge_ros1.message_codec import (
    decode_json_object,
    normalize_agent_payload,
    validate_command,
    validate_outgoing,
)


def env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


class FleetTextBridgeRos1:
    """MQTT <-> ROS 1 bridge for the SVERH fleet text protocol."""

    def __init__(self):
        self.robot_id = str(rospy.get_param("~robot_id", os.getenv("FLEET_ROBOT_ID", "drone-01"))).strip()
        self.host = str(
            rospy.get_param(
                "~mqtt_host",
                os.getenv("FLEET_MQTT_HOST", os.getenv("FLEET_SERVER_IP", "127.0.0.1")),
            )
        ).strip()
        self.port = int(rospy.get_param("~mqtt_port", env_int("FLEET_MQTT_PORT", 1883)))
        self.prefix = str(
            rospy.get_param("~mqtt_topic_prefix", os.getenv("FLEET_MQTT_TOPIC_PREFIX", "fleet/v1/robots"))
        ).rstrip("/")
        self.username = str(rospy.get_param("~mqtt_username", os.getenv("FLEET_MQTT_USERNAME", ""))).strip()
        self.password = os.getenv("FLEET_MQTT_PASSWORD", "")
        self.command_topic = str(
            rospy.get_param("~command_topic", os.getenv("AGENT_TEXT_COMMAND_TOPIC", "/agent/text_command"))
        )
        self.answer_topic = str(rospy.get_param("~answer_topic", os.getenv("AGENT_ANSWER_TOPIC", "/agent/answer")))
        self.status_topic = str(rospy.get_param("~status_topic", os.getenv("AGENT_STATUS_TOPIC", "/agent/status")))
        self.timeout = float(
            rospy.get_param("~agent_command_timeout_sec", env_float("FLEET_AGENT_COMMAND_TIMEOUT_SEC", 300.0))
        )

        if not self.robot_id:
            raise RuntimeError("FLEET_ROBOT_ID is empty")
        if not self.host:
            raise RuntimeError("FLEET_MQTT_HOST/FLEET_SERVER_IP is empty")

        self.command_mqtt = "%s/%s/command" % (self.prefix, self.robot_id)
        self.answer_mqtt = "%s/%s/answer" % (self.prefix, self.robot_id)
        self.status_mqtt = "%s/%s/status" % (self.prefix, self.robot_id)
        self.availability_mqtt = "%s/%s/availability" % (self.prefix, self.robot_id)

        self.incoming = queue.Queue()
        self.pending = deque()
        self.active = None
        self.active_since = None
        self.lock = threading.RLock()
        self.duplicates = DuplicateCache(env_int("FLEET_DUPLICATE_CACHE_SIZE", 100))

        self.command_pub = rospy.Publisher(self.command_topic, String, queue_size=10)
        rospy.Subscriber(self.answer_topic, String, self.on_ros_answer, queue_size=10)
        rospy.Subscriber(self.status_topic, String, self.on_ros_status, queue_size=10)

        self.client = self.make_client()
        if self.username:
            self.client.username_pw_set(self.username, self.password or None)
        self.client.will_set(
            self.availability_mqtt,
            json.dumps({"robot_id": self.robot_id, "online": False}),
            qos=1,
            retain=True,
        )
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=15)
        self.client.connect_async(self.host, self.port, 30)
        self.client.loop_start()

        rospy.Timer(rospy.Duration(0.05), self.tick)
        rospy.on_shutdown(self.shutdown)
        rospy.loginfo("Bridge %s connecting to MQTT %s:%s", self.robot_id, self.host, self.port)

    def make_client(self):
        kwargs = {"client_id": "bridge-%s" % self.robot_id, "clean_session": True}
        try:
            return mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1, **kwargs)
        except (AttributeError, TypeError):
            return mqtt.Client(**kwargs)

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc:
            rospy.logerr("MQTT connect failed rc=%s", rc)
            return
        client.subscribe(self.command_mqtt, qos=1)
        client.publish(
            self.availability_mqtt,
            json.dumps({"robot_id": self.robot_id, "online": True}),
            qos=1,
            retain=True,
        )
        rospy.loginfo("MQTT connected; subscribed to %s", self.command_mqtt)

    def on_disconnect(self, client, userdata, rc, properties=None):
        if rc:
            rospy.logwarn("Unexpected MQTT disconnect rc=%s", rc)

    def on_message(self, client, userdata, message):
        try:
            data = decode_json_object(message.payload)
            validate_command(data, self.robot_id)
            if self.duplicates.seen(data["message_id"]):
                rospy.logwarn("Duplicate ignored: %s", data["message_id"])
                return
            self.incoming.put(data)
        except Exception as exc:
            rospy.logerr("Invalid MQTT command: %s", exc)

    def active_id(self):
        with self.lock:
            return self.active.get("message_id") if isinstance(self.active, dict) else None

    def tick(self, _event):
        with self.lock:
            while True:
                try:
                    self.pending.append(self.incoming.get_nowait())
                except queue.Empty:
                    break

            if self.active is None and self.pending:
                self.active = self.pending.popleft()
                self.active_since = time.monotonic()
                self.command_pub.publish(String(data=json.dumps(self.active, ensure_ascii=False)))

            if self.active and self.timeout > 0 and time.monotonic() - self.active_since >= self.timeout:
                payload = {
                    "message_id": self.active_id(),
                    "robot_id": self.robot_id,
                    "status": "error",
                    "text": "Локальный агент не прислал ответ за %g с." % self.timeout,
                }
                self.client.publish(self.answer_mqtt, json.dumps(payload, ensure_ascii=False), qos=1)
                self.active = None
                self.active_since = None

    def on_ros_answer(self, msg):
        try:
            data = normalize_agent_payload(
                msg.data,
                expected_robot_id=self.robot_id,
                active_message_id=self.active_id(),
                answer=True,
            )
            validate_outgoing(data, self.robot_id, answer=True)
            self.client.publish(self.answer_mqtt, json.dumps(data, ensure_ascii=False), qos=1)
            with self.lock:
                if data["message_id"] == self.active_id():
                    self.active = None
                    self.active_since = None
        except Exception as exc:
            rospy.logerr("Invalid ROS answer: %s", exc)

    def on_ros_status(self, msg):
        try:
            data = normalize_agent_payload(
                msg.data,
                expected_robot_id=self.robot_id,
                active_message_id=self.active_id(),
                answer=False,
            )
            validate_outgoing(data, self.robot_id, answer=False)
            self.client.publish(self.status_mqtt, json.dumps(data, ensure_ascii=False), qos=1)
        except Exception as exc:
            rospy.logwarn("Ignored ROS status: %s", exc)

    def shutdown(self):
        try:
            self.client.publish(
                self.availability_mqtt,
                json.dumps({"robot_id": self.robot_id, "online": False}),
                qos=1,
                retain=True,
            )
            self.client.disconnect()
            self.client.loop_stop()
        except Exception:
            pass


def main():
    rospy.init_node("fleet_text_bridge")
    FleetTextBridgeRos1()
    rospy.spin()


if __name__ == "__main__":
    main()
