from __future__ import annotations

import math
import os
import threading
import time
import traceback
from typing import Any

import actionlib
from actionlib_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from nav_msgs.msg import Odometry
import rospy
from sensor_msgs.msg import LaserScan

try:
    from rover_interfaces.msg import LedStripState
    from rover_interfaces.srv import SetLedStripState, SetLedStripStateRequest
except ImportError:
    LedStripState = SetLedStripState = SetLedStripStateRequest = None

from rover_agent_mcp_ros1.tool_schemas import mcp_tools
from rover_agent_mcp_ros1.utils import clamp, clamp_int, color_to_hex, json_dumps, normalize_effect, parse_bool, parse_color, quaternion_to_yaw, yaw_to_quaternion


def env_float(name: str, default: float) -> float:
    try: return float(os.getenv(name, str(default)))
    except ValueError: return default


class RoverRos1Bridge:
    """ROS 1 tool backend matching the ROS 2 agent's public MCP tool names."""
    def __init__(self):
        self.cmd_vel_topic = os.getenv('ROVER_CMD_VEL_TOPIC', '/cmd_vel')
        self.odom_topic = os.getenv('ROVER_ODOM_TOPIC', '/odom')
        self.amcl_topic = os.getenv('ROVER_AMCL_POSE_TOPIC', '/amcl_pose')
        self.scan_topic = os.getenv('ROVER_SCAN_TOPIC', '/scan')
        self.nav_action = os.getenv('ROVER_NAV_ACTION', '/move_base')
        self.led_service = os.getenv('ROVER_LED_SERVICE', '/led_strip/set_state')
        self.led_state_topic = os.getenv('ROVER_LED_STATE_TOPIC', '/led_strip/state')
        self.speed = env_float('ROVER_DEFAULT_FORWARD_SPEED_MPS', 0.12)
        self.turn_speed = env_float('ROVER_DEFAULT_ANGULAR_SPEED_DEGPS', 45.0)
        self.position_tolerance = env_float('ROVER_POSITION_TOLERANCE_M', 0.025)
        self.yaw_tolerance = env_float('ROVER_YAW_TOLERANCE_DEG', 3.0)
        self.scan_front = env_float('ROVER_SCAN_FRONT_ANGLE_DEG', 0.0)
        self._lock = threading.RLock()
        self._odom = self._amcl = self._scan = self._led = None
        self._times = {'odom':0.0,'amcl':0.0,'scan':0.0,'led':0.0}
        self._nav_status = {'active':False,'status':'idle','message':'No goal.'}
        self._last_goal = None
        self.pub = rospy.Publisher(self.cmd_vel_topic, Twist, queue_size=10)
        rospy.Subscriber(self.odom_topic, Odometry, self._on_odom, queue_size=10)
        rospy.Subscriber(self.amcl_topic, PoseWithCovarianceStamped, self._on_amcl, queue_size=10)
        rospy.Subscriber(self.scan_topic, LaserScan, self._on_scan, queue_size=10)
        self.nav = actionlib.SimpleActionClient(self.nav_action, MoveBaseAction)
        self.led_proxy = None
        if LedStripState and SetLedStripState:
            rospy.Subscriber(self.led_state_topic, LedStripState, self._on_led, queue_size=10)
            self.led_proxy = rospy.ServiceProxy(self.led_service, SetLedStripState)
    def _on_odom(self,m): self._odom=m; self._times['odom']=time.monotonic()
    def _on_amcl(self,m): self._amcl=m; self._times['amcl']=time.monotonic()
    def _on_scan(self,m): self._scan=m; self._times['scan']=time.monotonic()
    def _on_led(self,m): self._led=m; self._times['led']=time.monotonic()
    def call_tool(self,name,arguments=None):
        aliases={'drive_forward':'drive_forward','run_relative_sequence':'run_motion_sequence'}
        fn=getattr(self, aliases.get(name,name), None)
        if not callable(fn): return {'success':False,'error':f'Unknown tool: {name}'}
        try: return fn(**dict(arguments or {}))
        except Exception as exc:
            rospy.logerr('Tool %s failed: %s\n%s',name,exc,traceback.format_exc()); return {'success':False,'error':str(exc),'tool':name}
    def get_available_tools(self): return {'success':True,'tools':[{'name':t['name'],'description':t.get('description','')} for t in mcp_tools()],'ros_version':1,'navigation_backend':'move_base'}
    def wait(self,duration_s=1.0):
        d=float(clamp(duration_s,0,60)); rospy.sleep(d); return {'success':True,'duration_s':d,'message':f'Waited {d:.2f} seconds.'}
    def _twist(self,x=0.0,y=0.0,z=0.0):
        m=Twist(); m.linear.x=float(x); m.linear.y=float(y); m.angular.z=float(z); return m
    def _stop(self): self.pub.publish(self._twist())
    def _pose(self):
        m=self._odom
        if not m: return None
        p=m.pose.pose; return p.position.x,p.position.y,quaternion_to_yaw(p.orientation.x,p.orientation.y,p.orientation.z,p.orientation.w)
    def _wait_odom(self,timeout=2.0):
        end=time.monotonic()+timeout
        while not rospy.is_shutdown() and not self._odom and time.monotonic()<end: rospy.sleep(0.02)
        return self._odom is not None
    def drive_relative(self,forward_m=0.30,left_m=0.0,speed_mps=None,timeout_s=None):
        if not self._wait_odom(): return {'success':False,'error':'No odometry received.'}
        tx=float(clamp(forward_m,-3,3)); ty=float(clamp(left_m,-3,3)); dist=math.hypot(tx,ty)
        if dist<1e-4: self._stop(); return {'success':True,'message':'Zero target.'}
        speed=float(clamp(abs(speed_mps if speed_mps is not None else self.speed),0.02,0.45)); tol=float(clamp(self.position_tolerance,0.005,0.2)); timeout=float(timeout_s or dist/speed+3)
        sx,sy,syaw=self._pose(); c,s=math.cos(syaw),math.sin(syaw); ux,uy=tx/dist,ty/dist; end=time.monotonic()+timeout; remain=dist; mx=my=0.0; rate=rospy.Rate(20)
        try:
            while not rospy.is_shutdown() and time.monotonic()<end:
                pose=self._pose()
                if not pose: break
                dx,dy=pose[0]-sx,pose[1]-sy; mx=c*dx+s*dy; my=-s*dx+c*dy; ex,ey=tx-mx,ty-my; remain=math.hypot(ex,ey)
                if remain<=tol: break
                v=min(speed,max(0.035,remain*1.2)); self.pub.publish(self._twist(ux*v,uy*v,0)); rate.sleep()
        finally: self._stop()
        ok=remain<=max(tol*2,0.05); return {'success':ok,'message':'Completed relative drive.' if ok else 'Drive stopped before tolerance.','remaining_m':remain,'measured_forward_m':mx,'measured_left_m':my}
    def drive_forward(self,distance_m=0.30,speed_mps=None,timeout_s=None): return self.drive_relative(distance_m,0.0,speed_mps,timeout_s)
    def turn_relative(self,angle_deg,angular_speed_degps=None,timeout_s=None):
        if not self._wait_odom(): return {'success':False,'error':'No odometry received.'}
        target=math.radians(float(clamp(angle_deg,-720,720))); start=self._pose()[2]; speed=math.radians(float(clamp(abs(angular_speed_degps or self.turn_speed),5,180))); tol=math.radians(float(clamp(self.yaw_tolerance,0.5,15))); end=time.monotonic()+float(timeout_s or abs(target)/speed+3); remain=abs(target); traveled=0.0; direction=1 if target>=0 else -1; rate=rospy.Rate(20)
        try:
            while not rospy.is_shutdown() and time.monotonic()<end:
                p=self._pose();
                if not p: break
                traveled=math.atan2(math.sin(p[2]-start),math.cos(p[2]-start)); remain=abs(target-traveled)
                if remain<=tol: break
                self.pub.publish(self._twist(z=direction*min(speed,max(math.radians(8),remain*1.5)))); rate.sleep()
        finally: self._stop()
        ok=remain<=max(tol*2,math.radians(5)); return {'success':ok,'message':'Completed relative turn.' if ok else 'Turn stopped before tolerance.','remaining_deg':math.degrees(remain),'measured_angle_deg':math.degrees(traveled)}
    def stop_motion(self,cancel_navigation=False):
        for _ in range(4): self._stop(); rospy.sleep(0.03)
        return {'success':True,'message':'Stopped.','navigation_cancel_result':self.cancel_navigation() if parse_bool(cancel_navigation,False) else None}
    def run_motion_sequence(self,steps,stop_on_error=True):
        if not isinstance(steps,list) or not steps: return {'success':False,'error':'steps must be a non-empty list'}
        results=[]; aliases={'drive':'drive_relative','move':'drive_relative','turn':'turn_relative','sleep':'wait'}
        for idx,raw in enumerate(steps):
            step=dict(raw or {}); typ=aliases.get(str(step.pop('type','')),str(raw.get('type','')))
            if typ=='drive_relative' and 'distance_m' in step and 'forward_m' not in step: step['forward_m']=step.pop('distance_m')
            result=self.call_tool(typ,step); result.update({'step_index':idx,'step_type':typ}); results.append(result)
            if parse_bool(stop_on_error,True) and not result.get('success'): self.stop_motion(); return {'success':False,'results':results}
        return {'success':True,'results':results}
    def navigate_to_pose(self,x,y,yaw_deg=0.0,frame_id='map',wait_until_done=False,timeout_s=60.0):
        if not self.nav.wait_for_server(rospy.Duration(3)): return {'success':False,'error':f'{self.nav_action} unavailable'}
        g=MoveBaseGoal(); g.target_pose.header.frame_id=frame_id; g.target_pose.header.stamp=rospy.Time.now(); g.target_pose.pose.position.x=float(x); g.target_pose.pose.position.y=float(y); q=yaw_to_quaternion(math.radians(float(yaw_deg))); g.target_pose.pose.orientation.x,g.target_pose.pose.orientation.y,g.target_pose.pose.orientation.z,g.target_pose.pose.orientation.w=q
        self._last_goal={'x':x,'y':y,'yaw_deg':yaw_deg,'frame_id':frame_id}; self.nav.send_goal(g); self._nav_status={'active':True,'status':'accepted','last_goal':self._last_goal}; result={'success':True,'message':'move_base goal accepted.','goal':self._last_goal}
        if parse_bool(wait_until_done,False):
            done=self.nav.wait_for_result(rospy.Duration(timeout_s)); state=self.nav.get_state(); ok=done and state==GoalStatus.SUCCEEDED; self._nav_status={'active':not done,'status':state,'last_goal':self._last_goal}; result.update({'success':ok,'goal_status':state})
        return result
    def cancel_navigation(self): self.nav.cancel_all_goals(); self._nav_status={'active':False,'status':'canceled','last_goal':self._last_goal}; return {'success':True,'message':'Canceled.'}
    def get_navigation_status(self): return {**self._nav_status,'server_ready':self.nav.wait_for_server(rospy.Duration(0.01)),'robot_pose':self.get_robot_pose()}
    def is_navigation_ready(self):
        pose=self.get_robot_pose(); ready=self.nav.wait_for_server(rospy.Duration(0.01)); return {'success':True,'ready':bool(ready and pose.get('success')),'server_ready':bool(ready),'pose_available':bool(pose.get('success'))}
    def get_robot_pose(self):
        m=self._amcl or self._odom
        if not m: return {'success':False,'error':'No pose or odometry received.'}
        p=m.pose.pose; source=self.amcl_topic if self._amcl else self.odom_topic; return {'success':True,'source':source,'frame':m.header.frame_id,'x':p.position.x,'y':p.position.y,'yaw_deg':math.degrees(quaternion_to_yaw(p.orientation.x,p.orientation.y,p.orientation.z,p.orientation.w))}
    def get_laser_summary(self):
        scan=self._scan
        if not scan: return {'success':False,'error':'No LaserScan received.'}
        def sec(center,width):
            vals=[]; c=math.radians(center); h=math.radians(width)/2
            for i,v in enumerate(scan.ranges):
                if not math.isfinite(v) or v<scan.range_min or v>scan.range_max: continue
                a=scan.angle_min+i*scan.angle_increment; d=math.atan2(math.sin(a-c),math.cos(a-c))
                if abs(d)<=h: vals.append(float(v))
            return min(vals) if vals else None
        f=self.scan_front; return {'success':True,'front_min_m':sec(f,40),'left_min_m':sec(f+90,60),'right_min_m':sec(f-90,60),'back_min_m':sec(f+180,60)}
    def set_led_strip(self,enabled=True,effect='fill',brightness=0.35,color='#16B8F3',secondary_color='#FFFFFF',effect_speed_hz=1.0):
        if not self.led_proxy or not SetLedStripStateRequest: return {'success':False,'error':'ROS1 rover_interfaces is not installed.'}
        try: rospy.wait_for_service(self.led_service,2)
        except rospy.ROSException: return {'success':False,'error':'LED service unavailable.'}
        r,g,b=parse_color(color); sr,sg,sb=parse_color(secondary_color); req=SetLedStripStateRequest(); req.enabled=parse_bool(enabled,True); req.brightness=float(clamp(brightness,0,1)); req.effect=normalize_effect(effect); req.effect_speed_hz=float(clamp(effect_speed_hz,0.05,20)); req.red,req.green,req.blue=clamp_int(r,0,255),clamp_int(g,0,255),clamp_int(b,0,255); req.secondary_red,req.secondary_green,req.secondary_blue=clamp_int(sr,0,255),clamp_int(sg,0,255),clamp_int(sb,0,255); resp=self.led_proxy(req); return {'success':bool(resp.success),'message':str(resp.message)}
    def set_led_preset(self,preset):
        presets={'off':dict(enabled=False,brightness=0,color='#000000'),'idle':dict(enabled=True,color='#16B8F3',brightness=0.18),'red':dict(enabled=True,color='#FF0000'),'green':dict(enabled=True,color='#00FF00'),'thinking':dict(enabled=True,effect='fade',color='#16B8F3'),'warning':dict(enabled=True,effect='blink_fast',color='#FF8000'),'success':dict(enabled=True,effect='flash',color='#00FF00'),'error':dict(enabled=True,effect='blink_fast',color='#FF0000')}; name=str(preset).lower();
        if name not in presets: return {'success':False,'error':f'Unknown preset: {preset}','available_presets':sorted(presets)}
        result=self.set_led_strip(**presets[name]); result['preset']=name; return result
    def blink_led_strip(self,color='#16B8F3',times=3,interval_s=0.35,brightness=0.35,restore='steady'):
        count=clamp_int(times,1,20)
        for _ in range(count): self.set_led_strip(True,'fill',brightness,color); rospy.sleep(interval_s); self.set_led_strip(False,'fill',0,'#000000'); rospy.sleep(interval_s)
        if str(restore).lower() in {'steady','on','previous'}: self.set_led_strip(True,'fill',brightness,color)
        return {'success':True,'times':count}
    def get_led_strip_state(self):
        if not self._led: return {'success':False,'error':'No LED state or interface.'}
        m=self._led; out={'success':True};
        for key in ('connected','enabled','led_count','lit_count','brightness','effect','effect_speed_hz','backend','transport','status_message'):
            if hasattr(m,key): out[key]=getattr(m,key)
        if all(hasattr(m,k) for k in ('red','green','blue')): out['color']=color_to_hex(m.red,m.green,m.blue)
        return out
    def get_system_status(self): return {'success':True,'ros_version':1,'cmd_vel_topic':self.cmd_vel_topic,'odom_received':self._odom is not None,'amcl_pose_received':self._amcl is not None,'scan_received':self._scan is not None,'led_backend_available':self.led_proxy is not None,'navigation':self.is_navigation_ready()}
    def result_to_text(self,result): return json_dumps(result)
