from __future__ import annotations

import json
import math
import os
import threading
import time
import traceback

import rospy
from std_srvs.srv import Trigger

from drone_agent_mcp_ros1.safety import DroneSafetyLimits, env_bool, finite_float
from drone_agent_mcp_ros1.tool_schemas import mcp_tools, sequence_step_argument_names
from drone_agent_mcp_ros1.utils import clamp, clamp_int, normalize_effect, parse_bool, parse_color


# SVERH images use the `sverk` service package. Upstream Clover uses `clover`.
try:
    from sverk import srv as flight_srv
    FLIGHT_SERVICE_PACKAGE = "sverk"
except ImportError:
    try:
        from clover import srv as flight_srv
        FLIGHT_SERVICE_PACKAGE = "clover"
    except ImportError:
        flight_srv = None
        FLIGHT_SERVICE_PACKAGE = None

try:
    from clover.srv import SetLEDEffect
except ImportError:
    try:
        from sverk.srv import SetLEDEffect
    except ImportError:
        SetLEDEffect = None


TELEMETRY_FIELDS = (
    "frame_id", "connected", "armed", "mode", "x", "y", "z",
    "lat", "lon", "alt", "vx", "vy", "vz", "roll", "pitch", "yaw",
    "roll_rate", "pitch_rate", "yaw_rate", "voltage", "cell_voltage",
)


def _safe_number(value):
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    return value


def _response_to_dict(response):
    result = {}
    for name in TELEMETRY_FIELDS:
        if hasattr(response, name):
            result[name] = _safe_number(getattr(response, name))
    if hasattr(response, "success"):
        result["success"] = bool(response.success)
    if hasattr(response, "message"):
        result["message"] = str(response.message)
    return result


class DroneRos1Bridge:
    """High-level, safety-limited MCP backend for ROS 1 SVERH/Clover."""

    def __init__(self):
        self.limits = DroneSafetyLimits()
        self.flight_requested = env_bool("DRONE_ENABLE_FLIGHT_TOOLS", False)
        self.allow_land_when_disabled = env_bool("DRONE_ALLOW_LAND_WHEN_DISABLED", True)
        self.land_on_sequence_error = env_bool("DRONE_LAND_ON_SEQUENCE_ERROR", False)
        self.lock = threading.RLock()

        self.service_names = {
            "telemetry": os.getenv("DRONE_GET_TELEMETRY_SERVICE", "get_telemetry"),
            "navigate": os.getenv("DRONE_NAVIGATE_SERVICE", "navigate"),
            "navigate_global": os.getenv("DRONE_NAVIGATE_GLOBAL_SERVICE", "navigate_global"),
            "set_altitude": os.getenv("DRONE_SET_ALTITUDE_SERVICE", "set_altitude"),
            "set_yaw": os.getenv("DRONE_SET_YAW_SERVICE", "set_yaw"),
            "set_position": os.getenv("DRONE_SET_POSITION_SERVICE", "set_position"),
            "land": os.getenv("DRONE_LAND_SERVICE", "land"),
            "led": os.getenv("DRONE_LED_EFFECT_SERVICE", "/led/set_effect"),
        }
        self.proxies = {}
        self._build_proxies()
        rospy.loginfo(
            "Drone MCP backend: services=%s, flight_tools=%s, max_altitude=%.2f, max_speed=%.2f",
            FLIGHT_SERVICE_PACKAGE or "missing",
            self.flight_requested,
            self.limits.max_altitude_m,
            self.limits.max_speed_mps,
        )
        if not self.flight_requested:
            rospy.logwarn("Flight commands are administratively locked by DRONE_ENABLE_FLIGHT_TOOLS=0.")

    def _flight_enabled(self):
        return bool(self.flight_requested)

    def _build_proxies(self):
        if flight_srv is not None:
            mappings = {
                "telemetry": "GetTelemetry",
                "navigate": "Navigate",
                "navigate_global": "NavigateGlobal",
                "set_altitude": "SetAltitude",
                "set_yaw": "SetYaw",
                "set_position": "SetPosition",
            }
            for key, class_name in mappings.items():
                service_type = getattr(flight_srv, class_name, None)
                if service_type is not None:
                    self.proxies[key] = rospy.ServiceProxy(self.service_names[key], service_type)
        self.proxies["land"] = rospy.ServiceProxy(self.service_names["land"], Trigger)
        if SetLEDEffect is not None:
            self.proxies["led"] = rospy.ServiceProxy(self.service_names["led"], SetLEDEffect)

    def _service_available(self, key, timeout=None):
        if key not in self.proxies:
            return False
        try:
            rospy.wait_for_service(
                self.service_names[key],
                timeout=self.limits.service_timeout_s if timeout is None else float(timeout),
            )
            return True
        except rospy.ROSException:
            return False

    def _call(self, key, **kwargs):
        if key not in self.proxies:
            return {"success": False, "error": "ROS service type for %s is unavailable" % key}
        if not self._service_available(key):
            return {
                "success": False,
                "error": "ROS service %s is unavailable" % self.service_names[key],
            }
        try:
            response = self.proxies[key](**kwargs)
            data = _response_to_dict(response)
            data.setdefault("success", True)
            data["service"] = self.service_names[key]
            return data
        except (rospy.ServiceException, rospy.ROSException) as exc:
            return {"success": False, "error": str(exc), "service": self.service_names[key]}

    def _require_flight_enabled(self, action, allow_safety_action=False):
        if self._flight_enabled():
            return None
        if allow_safety_action:
            return None
        return {
            "success": False,
            "error": "%s is locked. Set DRONE_ENABLE_FLIGHT_TOOLS=1 to allow flight tools." % action,
        }

    def _filtered_sequence_arguments(self, step_type, step):
        allowed_arguments = sequence_step_argument_names(step_type)
        if not allowed_arguments:
            return dict(step), []
        ignored = sorted(name for name in step if name not in allowed_arguments)
        return {name: value for name, value in step.items() if name in allowed_arguments}, ignored

    def call_tool(self, name, arguments=None):
        aliases = {
            "get_telemetry": "drone_get_telemetry",
            "takeoff": "drone_takeoff",
            "land": "drone_land",
            "navigate": "drone_navigate",
            "move_relative": "drone_move_relative",
            "hold_position": "drone_hold_position",
        }
        method_name = aliases.get(str(name), str(name))
        method = getattr(self, method_name, None)
        if not callable(method):
            return {"success": False, "error": "Unknown tool: %s" % name}
        try:
            with self.lock:
                return method(**dict(arguments or {}))
        except Exception as exc:
            rospy.logerr("Tool %s failed: %s\n%s", name, exc, traceback.format_exc())
            return {"success": False, "error": str(exc), "tool": name}

    def get_available_tools(self):
        return {
            "success": True,
            "tools": [{"name": t["name"], "description": t.get("description", "")} for t in mcp_tools()],
            "ros_version": 1,
            "platform": "SVERH/Clover",
            "service_package": FLIGHT_SERVICE_PACKAGE,
            "flight_tools_requested": self.flight_requested,
            "flight_tools_enabled": self._flight_enabled(),
            "land_on_sequence_error": self.land_on_sequence_error,
        }

    def wait(self, duration_s=1.0):
        duration = float(clamp(duration_s, 0.0, 60.0))
        rospy.sleep(duration)
        return {"success": True, "duration_s": duration, "message": "Wait complete."}

    def drone_get_telemetry(self, frame_id="map"):
        frame = self.limits.validate_frame(frame_id, allow_navigate_target=True)
        data = self._call("telemetry", frame_id=frame)
        if data.get("success"):
            yaw = data.get("yaw")
            if isinstance(yaw, (int, float)):
                data["yaw_deg"] = math.degrees(yaw)
            data["requested_frame_id"] = frame
        return data

    def drone_get_system_status(self):
        services = {}
        for key in ("telemetry", "navigate", "set_altitude", "set_yaw", "set_position", "land", "led"):
            services[key] = {
                "name": self.service_names[key],
                "available": self._service_available(key, timeout=0.25),
                "type_loaded": key in self.proxies,
            }
        telemetry = self.drone_get_telemetry("map") if services["telemetry"]["available"] else {
            "success": False,
            "error": "get_telemetry unavailable",
        }
        connected = bool(telemetry.get("connected")) if telemetry.get("success") else False
        ready = services["telemetry"]["available"] and services["navigate"]["available"] and connected
        return {
            "success": True,
            "ready_for_flight_commands": bool(ready and self._flight_enabled()),
            "flight_tools_requested": self.flight_requested,
            "flight_tools_enabled": self._flight_enabled(),
            "land_on_sequence_error": self.land_on_sequence_error,
            "telemetry_connected": connected,
            "armed": telemetry.get("armed"),
            "mode": telemetry.get("mode"),
            "voltage": telemetry.get("voltage"),
            "services": services,
            "safety_limits": {
                "max_altitude_m": self.limits.max_altitude_m,
                "min_flight_altitude_m": self.limits.min_flight_altitude_m,
                "max_speed_mps": self.limits.max_speed_mps,
                "max_horizontal_coordinate_m": self.limits.max_horizontal_coordinate_m,
                "max_relative_distance_m": self.limits.max_relative_distance_m,
                "allowed_frames": sorted(self.limits.allowed_frames),
            },
        }

    def _connected_telemetry(self):
        telemetry = self.drone_get_telemetry("map")
        if not telemetry.get("success"):
            return telemetry
        if self.limits.require_connected and not telemetry.get("connected"):
            return {"success": False, "error": "Flight controller is not connected", "telemetry": telemetry}
        return {"success": True, "telemetry": telemetry}

    def _preflight(self):
        connected = self._connected_telemetry()
        if not connected.get("success"):
            return connected
        telemetry = connected["telemetry"]
        if not telemetry.get("success"):
            return telemetry
        if self.limits.require_connected and not telemetry.get("connected"):
            return {"success": False, "error": "Flight controller is not connected", "telemetry": telemetry}
        voltage = telemetry.get("voltage")
        if (
            self.limits.min_takeoff_voltage_v > 0
            and isinstance(voltage, (int, float))
            and voltage < self.limits.min_takeoff_voltage_v
        ):
            return {
                "success": False,
                "error": "Voltage %.2f V is below DRONE_MIN_TAKEOFF_VOLTAGE_V %.2f V"
                % (voltage, self.limits.min_takeoff_voltage_v),
                "telemetry": telemetry,
            }
        return {"success": True, "telemetry": telemetry}

    def drone_takeoff(
        self,
        height_m=None,
        speed_mps=None,
        wait=True,
        tolerance_m=None,
        timeout_s=None,
    ):
        locked = self._require_flight_enabled("drone_takeoff")
        if locked:
            return locked
        preflight = self._preflight()
        if not preflight.get("success"):
            return preflight
        height = self.limits.validate_takeoff_height(height_m)
        speed = self.limits.validate_speed(speed_mps)
        response = self._call(
            "navigate",
            x=0.0,
            y=0.0,
            z=height,
            yaw=float("nan"),
            speed=speed,
            frame_id="body",
            auto_arm=True,
        )
        if not response.get("success") or not parse_bool(wait, True):
            return response
        arrival = self.drone_wait_until_arrival(tolerance_m=tolerance_m, timeout_s=timeout_s)
        return {
            "success": bool(arrival.get("success")),
            "command": response,
            "arrival": arrival,
            "height_m": height,
            "speed_mps": speed,
        }

    def drone_navigate(
        self,
        x,
        y,
        z,
        frame_id="map",
        speed_mps=None,
        yaw_deg=None,
        wait=True,
        tolerance_m=None,
        timeout_s=None,
    ):
        locked = self._require_flight_enabled("drone_navigate")
        if locked:
            return locked
        connected = self._connected_telemetry()
        if not connected.get("success"):
            return connected
        x, y, z, frame = self.limits.validate_absolute_target(x, y, z, frame_id)
        speed = self.limits.validate_speed(speed_mps)
        yaw = float("nan") if yaw_deg is None else math.radians(finite_float(yaw_deg, "yaw_deg"))
        response = self._call(
            "navigate",
            x=x,
            y=y,
            z=z,
            yaw=yaw,
            speed=speed,
            frame_id=frame,
            auto_arm=False,
        )
        if not response.get("success") or not parse_bool(wait, True):
            return response
        arrival = self.drone_wait_until_arrival(tolerance_m=tolerance_m, timeout_s=timeout_s)
        return {
            "success": bool(arrival.get("success")),
            "command": response,
            "arrival": arrival,
            "target": {"x": x, "y": y, "z": z, "frame_id": frame, "yaw_deg": yaw_deg},
        }

    def drone_move_relative(
        self,
        forward_m=0.5,
        left_m=0.0,
        up_m=0.0,
        speed_mps=None,
        yaw_deg=None,
        wait=True,
        tolerance_m=None,
        timeout_s=None,
    ):
        locked = self._require_flight_enabled("drone_move_relative")
        if locked:
            return locked
        connected = self._connected_telemetry()
        if not connected.get("success"):
            return connected
        current = connected.get("telemetry", {})
        forward, left, up = self.limits.validate_relative_target(forward_m, left_m, up_m)
        current_z = current.get("z")
        if isinstance(current_z, (int, float)):
            estimated_z = float(current_z) + up
            if estimated_z < self.limits.min_flight_altitude_m or estimated_z > self.limits.max_altitude_m:
                return {
                    "success": False,
                    "error": "Estimated target altitude %.2f m is outside the configured safety envelope" % estimated_z,
                    "current_z": current_z,
                    "up_m": up,
                }
        speed = self.limits.validate_speed(speed_mps)
        yaw = float("nan") if yaw_deg is None else math.radians(finite_float(yaw_deg, "yaw_deg"))
        response = self._call(
            "navigate",
            x=forward,
            y=left,
            z=up,
            yaw=yaw,
            speed=speed,
            frame_id="body",
            auto_arm=False,
        )
        if not response.get("success") or not parse_bool(wait, True):
            return response
        arrival = self.drone_wait_until_arrival(tolerance_m=tolerance_m, timeout_s=timeout_s)
        return {
            "success": bool(arrival.get("success")),
            "command": response,
            "arrival": arrival,
            "relative_target": {"forward_m": forward, "left_m": left, "up_m": up},
        }

    def drone_set_altitude(self, z, frame_id="terrain"):
        locked = self._require_flight_enabled("drone_set_altitude")
        if locked:
            return locked
        connected = self._connected_telemetry()
        if not connected.get("success"):
            return connected
        frame = self.limits.validate_frame(frame_id)
        altitude = finite_float(z, "z")
        if frame != "body":
            if altitude < self.limits.min_flight_altitude_m or altitude > self.limits.max_altitude_m:
                raise ValueError(
                    "Altitude must be between %.2f and %.2f m"
                    % (self.limits.min_flight_altitude_m, self.limits.max_altitude_m)
                )
        elif abs(altitude) > self.limits.max_relative_vertical_m:
            raise ValueError("Relative altitude change exceeds DRONE_MAX_RELATIVE_VERTICAL_M")
        return self._call("set_altitude", z=altitude, frame_id=frame)

    def drone_set_yaw(self, yaw_deg=None, relative_deg=None, frame_id="map"):
        locked = self._require_flight_enabled("drone_set_yaw")
        if locked:
            return locked
        connected = self._connected_telemetry()
        if not connected.get("success"):
            return connected
        if yaw_deg is None and relative_deg is None:
            raise ValueError("Set yaw_deg or relative_deg")
        if relative_deg is not None:
            yaw = math.radians(finite_float(relative_deg, "relative_deg"))
            frame = "body"
        else:
            yaw = math.radians(finite_float(yaw_deg, "yaw_deg"))
            frame = self.limits.validate_frame(frame_id)
        return self._call("set_yaw", yaw=yaw, frame_id=frame)

    def drone_hold_position(self, frame_id="map"):
        locked = self._require_flight_enabled("drone_hold_position", allow_safety_action=True)
        if locked:
            return locked
        frame = self.limits.validate_frame(frame_id)
        telemetry = self.drone_get_telemetry(frame)
        if not telemetry.get("success"):
            return telemetry
        for field in ("x", "y", "z", "yaw"):
            if not isinstance(telemetry.get(field), (int, float)):
                return {"success": False, "error": "Telemetry field %s is unavailable" % field}
        response = self._call(
            "set_position",
            x=float(telemetry["x"]),
            y=float(telemetry["y"]),
            z=float(telemetry["z"]),
            yaw=float(telemetry["yaw"]),
            frame_id=frame,
            auto_arm=False,
        )
        response["held_pose"] = {
            "x": telemetry["x"],
            "y": telemetry["y"],
            "z": telemetry["z"],
            "yaw_deg": telemetry.get("yaw_deg"),
            "frame_id": frame,
        }
        return response

    def drone_wait_until_arrival(self, tolerance_m=None, timeout_s=None):
        tolerance = self.limits.arrival_tolerance_m if tolerance_m is None else finite_float(tolerance_m, "tolerance_m")
        timeout = self.limits.navigation_timeout_s if timeout_s is None else finite_float(timeout_s, "timeout_s")
        tolerance = float(clamp(tolerance, 0.05, 2.0))
        timeout = float(clamp(timeout, 0.5, 600.0))
        deadline = time.monotonic() + timeout
        last_distance = None
        while not rospy.is_shutdown() and time.monotonic() < deadline:
            telemetry = self.drone_get_telemetry("navigate_target")
            if not telemetry.get("success"):
                return telemetry
            coords = [telemetry.get("x"), telemetry.get("y"), telemetry.get("z")]
            if not all(isinstance(v, (int, float)) for v in coords):
                return {"success": False, "error": "navigate_target telemetry is incomplete", "telemetry": telemetry}
            last_distance = math.sqrt(sum(float(v) ** 2 for v in coords))
            if last_distance <= tolerance:
                return {
                    "success": True,
                    "distance_m": last_distance,
                    "tolerance_m": tolerance,
                    "message": "Target reached within tolerance.",
                }
            rospy.sleep(0.2)
        return {
            "success": False,
            "error": "Arrival timeout after %.1f s" % timeout,
            "distance_m": last_distance,
            "tolerance_m": tolerance,
        }

    def drone_land(self, wait_until_disarmed=False, timeout_s=60.0):
        if not self._flight_enabled() and not self.allow_land_when_disabled:
            return self._require_flight_enabled("drone_land")
        response = self._call("land")
        if not response.get("success") or not parse_bool(wait_until_disarmed, False):
            return response
        timeout = float(clamp(finite_float(timeout_s, "timeout_s"), 1.0, 300.0))
        deadline = time.monotonic() + timeout
        while not rospy.is_shutdown() and time.monotonic() < deadline:
            telemetry = self.drone_get_telemetry("map")
            if telemetry.get("success") and telemetry.get("armed") is False:
                response["disarmed"] = True
                return response
            rospy.sleep(0.5)
        response.update({"success": False, "error": "Landing command sent, but disarm was not observed before timeout"})
        return response

    def drone_set_led_effect(self, effect="fill", color="#16B8F3", r=None, g=None, b=None):
        effect_name = normalize_effect(effect)
        if r is None or g is None or b is None:
            red, green, blue = parse_color(color)
        else:
            red, green, blue = clamp_int(r, 0, 255), clamp_int(g, 0, 255), clamp_int(b, 0, 255)
        response = self._call("led", effect=effect_name, r=red, g=green, b=blue)
        response["effect"] = effect_name
        response["rgb"] = [red, green, blue]
        return response

    def drone_run_sequence(self, steps, stop_on_error=True):
        if not isinstance(steps, list) or not steps:
            return {"success": False, "error": "steps must be a non-empty list"}
        if len(steps) > 20:
            return {"success": False, "error": "steps length exceeds 20"}
        results = []
        allowed = {
            "drone_takeoff", "drone_navigate", "drone_move_relative", "drone_set_altitude",
            "drone_set_yaw", "drone_hold_position", "drone_set_led_effect", "wait", "drone_land",
        }
        for index, raw in enumerate(steps):
            step = dict(raw or {})
            step_type = str(step.pop("type", ""))
            if step_type not in allowed:
                result = {"success": False, "error": "Unsupported sequence step: %s" % step_type}
            else:
                filtered_step, ignored_arguments = self._filtered_sequence_arguments(step_type, step)
                result = self.call_tool(step_type, filtered_step)
                if ignored_arguments:
                    result = dict(result)
                    result["ignored_arguments"] = ignored_arguments
                    rospy.logwarn(
                        "Ignoring unsupported arguments for sequence step %s: %s",
                        step_type,
                        ", ".join(ignored_arguments),
                    )
            result = dict(result)
            result.update({"step_index": index, "step_type": step_type})
            results.append(result)
            if parse_bool(stop_on_error, True) and not result.get("success"):
                successful_takeoff = any(
                    item.get("step_type") == "drone_takeoff" and bool(item.get("success"))
                    for item in results
                )
                if self.land_on_sequence_error and successful_takeoff:
                    landing_result = self.drone_land(wait_until_disarmed=False)
                    if landing_result.get("success"):
                        return {
                            "success": False,
                            "results": results,
                            "sequence_error_action": "land",
                            "sequence_error_land": landing_result,
                        }
                    hold_result = self.drone_hold_position()
                    return {
                        "success": False,
                        "results": results,
                        "sequence_error_action": "land_then_hold",
                        "sequence_error_land": landing_result,
                        "safety_hold": hold_result,
                    }
                # Hold is safer than silently continuing when we stay airborne after an error.
                hold_result = self.drone_hold_position()
                return {
                    "success": False,
                    "results": results,
                    "sequence_error_action": "hold",
                    "safety_hold": hold_result,
                }
        return {"success": True, "results": results}
