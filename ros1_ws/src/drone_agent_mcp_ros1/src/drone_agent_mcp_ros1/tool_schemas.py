from copy import deepcopy


def _const_string_schema(value):
    return {"type": "string", "const": value}


SEQUENCE_STEP_SCHEMAS = {
    "drone_takeoff": {
        "type": "object",
        "properties": {
            "type": _const_string_schema("drone_takeoff"),
            "height_m": {"type": "number"},
            "speed_mps": {"type": "number"},
            "wait": {"type": "boolean"},
            "tolerance_m": {"type": "number"},
            "timeout_s": {"type": "number"},
        },
        "required": ["type"],
        "additionalProperties": False,
    },
    "drone_navigate": {
        "type": "object",
        "properties": {
            "type": _const_string_schema("drone_navigate"),
            "x": {"type": "number"},
            "y": {"type": "number"},
            "z": {"type": "number"},
            "frame_id": {"type": "string"},
            "speed_mps": {"type": "number"},
            "yaw_deg": {"type": ["number", "null"]},
            "wait": {"type": "boolean"},
            "tolerance_m": {"type": "number"},
            "timeout_s": {"type": "number"},
        },
        "required": ["type", "x", "y", "z"],
        "additionalProperties": False,
    },
    "drone_move_relative": {
        "type": "object",
        "properties": {
            "type": _const_string_schema("drone_move_relative"),
            "forward_m": {"type": "number"},
            "left_m": {"type": "number"},
            "up_m": {"type": "number"},
            "speed_mps": {"type": "number"},
            "yaw_deg": {"type": ["number", "null"]},
            "wait": {"type": "boolean"},
            "tolerance_m": {"type": "number"},
            "timeout_s": {"type": "number"},
        },
        "required": ["type"],
        "additionalProperties": False,
    },
    "drone_set_altitude": {
        "type": "object",
        "properties": {
            "type": _const_string_schema("drone_set_altitude"),
            "z": {"type": "number"},
            "frame_id": {"type": "string"},
        },
        "required": ["type", "z"],
        "additionalProperties": False,
    },
    "drone_set_yaw": {
        "type": "object",
        "properties": {
            "type": _const_string_schema("drone_set_yaw"),
            "yaw_deg": {"type": ["number", "null"]},
            "relative_deg": {"type": ["number", "null"]},
            "frame_id": {"type": "string"},
        },
        "required": ["type"],
        "anyOf": [{"required": ["yaw_deg"]}, {"required": ["relative_deg"]}],
        "additionalProperties": False,
    },
    "drone_hold_position": {
        "type": "object",
        "properties": {
            "type": _const_string_schema("drone_hold_position"),
            "frame_id": {"type": "string"},
        },
        "required": ["type"],
        "additionalProperties": False,
    },
    "drone_set_led_effect": {
        "type": "object",
        "properties": {
            "type": _const_string_schema("drone_set_led_effect"),
            "effect": {"type": "string"},
            "color": {"type": "string"},
            "r": {"type": ["integer", "null"]},
            "g": {"type": ["integer", "null"]},
            "b": {"type": ["integer", "null"]},
        },
        "required": ["type"],
        "additionalProperties": False,
    },
    "wait": {
        "type": "object",
        "properties": {
            "type": _const_string_schema("wait"),
            "duration_s": {"type": "number"},
        },
        "required": ["type"],
        "additionalProperties": False,
    },
    "drone_land": {
        "type": "object",
        "properties": {
            "type": _const_string_schema("drone_land"),
            "wait_until_disarmed": {"type": "boolean"},
            "timeout_s": {"type": "number"},
        },
        "required": ["type"],
        "additionalProperties": False,
    },
}


TOOL_SCHEMAS = [
    {
        "name": "get_available_tools",
        "description": "List all MCP tools available on this Clover drone.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "wait",
        "description": "Wait without changing the current flight target.",
        "inputSchema": {
            "type": "object",
            "properties": {"duration_s": {"type": "number", "minimum": 0.0, "maximum": 60.0, "default": 1.0}},
            "additionalProperties": False,
        },
    },
    {
        "name": "drone_get_telemetry",
        "description": "Return Clover telemetry: connection, armed state, mode, position, velocity, yaw, voltage and GPS fields.",
        "inputSchema": {
            "type": "object",
            "properties": {"frame_id": {"type": "string", "default": "map"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "drone_get_system_status",
        "description": "Check required simple_offboard services, LED service, telemetry connection and local safety limits.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "drone_takeoff",
        "description": "Safely arm in OFFBOARD and take off vertically relative to the current body frame, optionally waiting for arrival.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "height_m": {"type": "number", "default": 1.0},
                "speed_mps": {"type": "number", "default": 0.15},
                "wait": {"type": "boolean", "default": True},
                "tolerance_m": {"type": "number", "default": 0.25},
                "timeout_s": {"type": "number", "default": 60.0},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "drone_land",
        "description": "Switch the flight controller to landing mode. Use only for an intentional landing, not for stop/hold.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "wait_until_disarmed": {"type": "boolean", "default": False},
                "timeout_s": {"type": "number", "default": 60.0},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "drone_navigate",
        "description": "Fly to an absolute point using Clover navigate. yaw_deg may be omitted to keep current yaw. Never auto-arms.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "z": {"type": "number"},
                "frame_id": {"type": "string", "default": "map"},
                "speed_mps": {"type": "number", "default": 0.5},
                "yaw_deg": {"type": ["number", "null"], "default": None},
                "wait": {"type": "boolean", "default": True},
                "tolerance_m": {"type": "number", "default": 0.25},
                "timeout_s": {"type": "number", "default": 60.0},
            },
            "required": ["x", "y", "z"],
            "additionalProperties": False,
        },
    },
    {
        "name": "drone_navigate_to_chess_cell",
        "description": "Take off if needed, localize in aruco_map, then fly along the chessboard axes to the target cell a1..h8 and optionally land.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cell": {"type": "string", "pattern": "^[a-h][1-8]$"},
                "takeoff_height_m": {"type": ["number", "null"], "default": None},
                "flight_altitude_m": {"type": ["number", "null"], "default": None},
                "speed_mps": {"type": "number", "default": 0.5},
                "takeoff_speed_mps": {"type": "number", "default": 0.15},
                "land_after": {"type": "boolean", "default": True},
                "wait_for_map_s": {"type": "number", "default": 10.0},
                "land_wait_until_disarmed": {"type": "boolean", "default": False},
                "land_timeout_s": {"type": ["number", "null"], "default": None},
                "arrival_tolerance_m": {"type": "number", "default": 0.10},
                "settle_duration_s": {"type": "number", "default": 2.0},
                "settle_timeout_s": {"type": "number", "default": 10.0},
                "camera_forward_compensation_m": {"type": "number", "default": 0.125},
            },
            "required": ["cell"],
            "additionalProperties": False,
        },
    },
    {
        "name": "drone_move_relative",
        "description": "Move relative to the drone body: +forward, +left, +up. Negative values move backward/right/down.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "forward_m": {"type": "number", "default": 0.5},
                "left_m": {"type": "number", "default": 0.0},
                "up_m": {"type": "number", "default": 0.0},
                "speed_mps": {"type": "number", "default": 0.5},
                "yaw_deg": {"type": ["number", "null"], "default": None},
                "wait": {"type": "boolean", "default": True},
                "tolerance_m": {"type": "number", "default": 0.25},
                "timeout_s": {"type": "number", "default": 60.0},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "drone_set_altitude",
        "description": "Change only the altitude target using set_altitude, without replacing the horizontal target.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "z": {"type": "number"},
                "frame_id": {"type": "string", "default": "terrain"},
            },
            "required": ["z"],
            "additionalProperties": False,
        },
    },
    {
        "name": "drone_set_yaw",
        "description": "Change only yaw. Use yaw_deg for an angle in a frame or relative_deg for a body-relative turn.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "yaw_deg": {"type": ["number", "null"], "default": None},
                "relative_deg": {"type": ["number", "null"], "default": None},
                "frame_id": {"type": "string", "default": "map"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "drone_hold_position",
        "description": "Stop current translation and hold the current pose. This is the correct tool for stop/hover while airborne.",
        "inputSchema": {
            "type": "object",
            "properties": {"frame_id": {"type": "string", "default": "map"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "drone_wait_until_arrival",
        "description": "Wait until distance in navigate_target is below tolerance. Usually called internally by navigation tools.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tolerance_m": {"type": "number", "default": 0.25},
                "timeout_s": {"type": "number", "default": 60.0},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "drone_set_led_effect",
        "description": "Set Clover LED strip effect and RGB color through /led/set_effect.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "effect": {
                    "type": "string",
                    "enum": ["fill", "blink", "blink_fast", "fade", "wipe", "flash", "rainbow", "rainbow_fill"],
                    "default": "fill",
                },
                "color": {"type": "string", "default": "#16B8F3"},
                "r": {"type": ["integer", "null"], "minimum": 0, "maximum": 255, "default": None},
                "g": {"type": ["integer", "null"], "minimum": 0, "maximum": 255, "default": None},
                "b": {"type": ["integer", "null"], "minimum": 0, "maximum": 255, "default": None},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "drone_run_sequence",
        "description": "Run a safe sequence of takeoff, navigate, relative move, yaw, altitude, LED, wait, hold, and land actions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": {"oneOf": [deepcopy(schema) for schema in SEQUENCE_STEP_SCHEMAS.values()]},
                },
                "stop_on_error": {"type": "boolean", "default": True},
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
]


def mcp_tools():
    return deepcopy(TOOL_SCHEMAS)


def tool_names():
    return {item["name"] for item in TOOL_SCHEMAS}


def sequence_step_argument_names(step_type):
    schema = SEQUENCE_STEP_SCHEMAS.get(step_type)
    if not schema:
        return set()
    return {name for name in schema["properties"] if name != "type"}
