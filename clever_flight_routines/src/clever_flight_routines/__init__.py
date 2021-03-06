#!/usr/bin/env python
import sys
import csv
import math
import time
import logging
import threading
import rospy
import copy
from clever import srv
from mavros_msgs.srv import SetMode
from mavros_msgs.srv import CommandBool
from std_srvs.srv import Trigger

# Create proxies to services
navigate = rospy.ServiceProxy('/navigate', srv.Navigate)
navigate_global = rospy.ServiceProxy('/navigate_global', srv.NavigateGlobal)
set_position = rospy.ServiceProxy('/set_position', srv.SetPosition)
set_velocity = rospy.ServiceProxy('/set_velocity', srv.SetVelocity)
set_attitude = rospy.ServiceProxy('/set_attitude', srv.SetAttitude)
set_rates = rospy.ServiceProxy('/set_rates', srv.SetRates)
get_telemetry = rospy.ServiceProxy('/get_telemetry', srv.GetTelemetry)
land = rospy.ServiceProxy('/land', Trigger)
arming = rospy.ServiceProxy('/mavros/cmd/arming', CommandBool)
set_mode = rospy.ServiceProxy('/mavros/set_mode', SetMode)

rospy.logdebug("Proxy services inited")

# Globals
FREQUENCY = 10              # hz
TOLERANCE = 0.2             # m
SPEED = 1.0                 # m/s
TAKEOFF_SPEED = 1.0         # m/s
TAKEOFF_HEIGHT = 1.0        # m
LOCAL_FRAME_ID = 'map'
COPTER_FRAME_ID = 'body'

# Get distance betwen 2 points
def get_distance(x1, y1, z1, x2, y2, z2):
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)

# Takeoff to specified height
def takeoff(height=TAKEOFF_HEIGHT, speed=TAKEOFF_SPEED, tolerance=TOLERANCE, frame_id=LOCAL_FRAME_ID):
    rospy.loginfo("Takeoff started...")
    rate = rospy.Rate(FREQUENCY)
    start = get_telemetry(frame_id=frame_id)
    climb = 0.
    result = navigate(x=start.x, y=start.y, z=start.z+height, speed=speed, yaw=float('nan'), frame_id=frame_id, auto_arm=True)
    rospy.logdebug(result)
    while abs(climb - height) > tolerance:
        climb = abs(get_telemetry(frame_id=frame_id).z - start.z)
        rospy.logdebug("Takeoff to {:.2f} of {:.2f} meters".format(climb, height))
        rate.sleep()
    rospy.loginfo("Takeoff succeeded!")

# Reach specified point. Copter needs to be armed.
def reach_point(x, y, z, yaw=float('nan'), speed=SPEED, tolerance=TOLERANCE, frame_id=LOCAL_FRAME_ID):
    rospy.loginfo("Reaching point {:.2f} {:.2f} {:.2f}".format(x, y, z))
    rate = rospy.Rate(FREQUENCY)
    telem = get_telemetry(frame_id=frame_id)
    result = navigate(x=x, y=y, z=z, yaw=yaw, speed=speed, frame_id=frame_id)
    rospy.logdebug(result)
    delta = get_distance(x, y, z, telem.x, telem.y, telem.z)
    while delta > tolerance:
        telem = get_telemetry(frame_id=frame_id)
        delta = get_distance(x, y, z, telem.x, telem.y, telem.z)
        rospy.logdebug("Distance remaining: {:.2f} m".format(delta))
        rate.sleep()
    rospy.loginfo("Point reached!")

# Create route file. add_trigger and stop_trigger are external controlled threading.Event variables for add point and end creating operations.
def create_route(filename, add_trigger, stop_trigger, frame_id=LOCAL_FRAME_ID):
    csv_file = open(filename, mode='w+')
    rospy.loginfo('Open file {} for writing route'.format(filename))
    rate = rospy.Rate(FREQUENCY)
    with csv_file:
        csv_writer = csv.writer(csv_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        while not stop_trigger.is_set():
            while not add_trigger.is_set():
                if stop_trigger.is_set():
                    rospy.loginfo('Route {} is created'.format(filename))
                    return
                rate.sleep()
            telem = get_telemetry(frame_id=frame_id)
            csv_writer.writerow([telem.x, telem.y, telem.z])
            rospy.loginfo('Add point {:.3f}, {:.3f}, {:.3f} to {}'.format(telem.x, telem.y, telem.z, filename))
            while add_trigger.is_set():
                if stop_trigger.is_set():
                    rospy.loginfo('Route {} is created'.format(filename))
                    return
                rate.sleep()
    rospy.loginfo('Route {} is created'.format(filename))

# Read array of points from csv file
def read_route(filename):
    imported_points = []
    try:
        csv_file = open(filename)
    except IOError:
        logging.error("File {} can't be opened".format(filename))
    else:
        with csv_file:
            csv_reader = csv.reader(csv_file, delimiter=',', quotechar='|')
            for row in csv_reader:
                x, y, z = row
                imported_points.append({
                    'x': float(x),
                    'y': float(y),
                    'z': float(z),
                })
        return imported_points

# Fly route with specified flight function (navigate, set_position or reach_point). Copter needs to be armed.
def fly_route(route, flight_function=reach_point, z = float('nan'), delay = 0.1, speed=SPEED, frame_id=LOCAL_FRAME_ID):        
    for point in route:
        z_result = point['z']
        if not math.isnan(z):
            z_result = z
        flight_function(x=point['x'], y=point['y'], z=z_result, speed=speed, frame_id=frame_id)
        time.sleep(delay)
