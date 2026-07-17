#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import traceback
from urllib.parse import urlparse

import rospy

from drone_agent_mcp_ros1.drone_ros_bridge import DroneRos1Bridge
from drone_agent_mcp_ros1.tool_schemas import mcp_tools
from drone_agent_mcp_ros1.utils import json_dumps


class McpHttpHandler(BaseHTTPRequestHandler):
    def send_json(self, code, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlparse(self.path).path in {"/", "/health", "/mcp"}:
            self.send_json(
                200,
                {
                    "ok": True,
                    "name": "drone_mcp_server_ros1",
                    "robot_id": os.getenv("FLEET_ROBOT_ID", "drone-01"),
                    "flight_tools_requested": os.getenv("DRONE_ENABLE_FLIGHT_TOOLS", "0") == "1",
                    "land_on_sequence_error": os.getenv("DRONE_LAND_ON_SEQUENCE_ERROR", "0") == "1",
                },
            )
            return
        self.send_json(404, {"ok": False, "error": "Not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/mcp":
            self.send_json(404, {"jsonrpc": "2.0", "id": None, "error": {"code": -32004, "message": "Not found"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception as exc:
            self.send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}})
            return
        self.send_json(200, self.server.rpc(request))

    def log_message(self, *args):
        return


class DroneMcpHttpServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address, bridge):
        super().__init__(address, McpHttpHandler)
        self.bridge = bridge

    def rpc(self, request):
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            method = request.get("method", "")
            params = request.get("params") or {}
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "drone_mcp_server_ros1", "version": "1.0.0"},
                    "capabilities": {"tools": {}},
                }
            elif method == "tools/list":
                result = {"tools": mcp_tools()}
            elif method == "tools/call":
                tool = str(params.get("name", ""))
                arguments = params.get("arguments") or {}
                rospy.loginfo("MCP tool call: %s %s", tool, json_dumps(arguments))
                structured = self.bridge.call_tool(tool, arguments)
                result = {
                    "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
                    "isError": not bool(structured.get("success")),
                    "structuredContent": structured,
                }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": "Method not found: %s" % method},
                }
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:
            rospy.logerr("%s\n%s", exc, traceback.format_exc())
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": str(exc)},
            }


def main():
    rospy.init_node("drone_mcp_server")
    bridge = DroneRos1Bridge()
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8765"))
    try:
        server = DroneMcpHttpServer((host, port), bridge)
    except OSError as exc:
        rospy.logfatal(
            "Cannot bind MCP server to %s:%s: %s. Stop the old MCP process or change MCP_PORT/MCP_URL.",
            host,
            port,
            exc,
        )
        raise
    threading.Thread(target=server.serve_forever, daemon=True).start()
    rospy.loginfo("ROS1 drone MCP server at http://%s:%s/mcp", host, port)
    rospy.on_shutdown(lambda: (server.shutdown(), server.server_close()))
    rospy.spin()


if __name__ == "__main__":
    main()
