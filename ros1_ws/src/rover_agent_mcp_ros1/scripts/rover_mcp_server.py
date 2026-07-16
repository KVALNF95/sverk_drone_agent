#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, os, threading, traceback
from urllib.parse import urlparse
import rospy
from rover_agent_mcp_ros1.ros_bridge import RoverRos1Bridge
from rover_agent_mcp_ros1.tool_schemas import mcp_tools
from rover_agent_mcp_ros1.utils import json_dumps

class Handler(BaseHTTPRequestHandler):
    def send_json(self,code,payload):
        data=json.dumps(payload,ensure_ascii=False).encode(); self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if urlparse(self.path).path in {'/','/health','/mcp'}: self.send_json(200,{'ok':True,'name':'rover_mcp_server_ros1'}); return
        self.send_json(404,{'ok':False,'error':'Not found'})
    def do_POST(self):
        if urlparse(self.path).path!='/mcp': self.send_json(404,{'jsonrpc':'2.0','id':None,'error':{'code':-32004,'message':'Not found'}}); return
        try: req=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))).decode() or '{}')
        except Exception as exc: self.send_json(400,{'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':str(exc)}}); return
        self.send_json(200,self.server.rpc(req))
    def log_message(self,*args): pass
class Server(ThreadingHTTPServer):
    def __init__(self,address,bridge): super().__init__(address,Handler); self.bridge=bridge
    def rpc(self,request):
        rid=request.get('id') if isinstance(request,dict) else None
        try:
            method=request.get('method',''); params=request.get('params') or {}
            if method=='initialize': result={'protocolVersion':'2024-11-05','serverInfo':{'name':'rover_mcp_server_ros1','version':'1.0.0'},'capabilities':{'tools':{}}}
            elif method=='tools/list': result={'tools':mcp_tools()}
            elif method=='tools/call':
                tool=str(params.get('name','')); args=params.get('arguments') or {}; rospy.loginfo('MCP tool call: %s %s',tool,json_dumps(args)); structured=self.bridge.call_tool(tool,args); result={'content':[{'type':'text','text':json.dumps(structured,ensure_ascii=False)}],'isError':not bool(structured.get('success')),'structuredContent':structured}
            else: return {'jsonrpc':'2.0','id':rid,'error':{'code':-32601,'message':f'Method not found: {method}'}}
            return {'jsonrpc':'2.0','id':rid,'result':result}
        except Exception as exc: rospy.logerr('%s\n%s',exc,traceback.format_exc()); return {'jsonrpc':'2.0','id':rid,'error':{'code':-32603,'message':str(exc)}}
def main():
    rospy.init_node('rover_mcp_server'); bridge=RoverRos1Bridge(); host=os.getenv('MCP_HOST','127.0.0.1'); port=int(os.getenv('MCP_PORT','8765')); server=Server((host,port),bridge); threading.Thread(target=server.serve_forever,daemon=True).start(); rospy.loginfo('ROS1 MCP server at http://%s:%s/mcp',host,port); rospy.on_shutdown(lambda:(server.shutdown(),server.server_close())); rospy.spin()
if __name__=='__main__': main()
