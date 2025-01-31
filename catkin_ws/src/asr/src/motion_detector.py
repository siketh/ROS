#!/usr/bin/env python

import cv2, rospy, roslib
import time, numpy as np
from std_msgs.msg import String, Bool
from sensor_msgs.msg import Image
from cv_bridge import CvBridge, CvBridgeError
roslib.load_manifest('asr')

state = None
motion_detection = False
camera_img = None
md_halted = True
md_ready = False
bridge = CvBridge()

def state_callback(data):
    global state

    state = data.data
    if state == "Shutdown":
        rospy.signal_shutdown(shutdown_hook())


def shutdown_hook():
    print("\n...MOTION DETECTOR SHUTTING DOWN...")


def image_callback(data):
    global camera_img, bridge

    try:
        camera_img = bridge.imgmsg_to_cv2(data, "bgr8")
        image_sub.unregister()
    except CvBridgeError, e:
        print e


def md_callback(data):
    global motion_detection
    motion_detection = data.data


def md_ready_callback(data):
    global md_ready
    md_ready = data.data


def halt_md_callback(data):
    global md_halted
    md_halted = data.data


# motion tracking function which detects largest contour in thresholded/blurred image and draws a bounding target
# around it
def track_motion(t_b_img, bgr_img):

    t_b = t_b_img.copy()
    bgr = bgr_img.copy()
    final_img = bgr.copy()

    now = time.strftime("%c")

    # find contours in the image
    image, contours, hierarchy = cv2.findContours(t_b, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    # if countours exist, there there is motion in the image
    if len(contours) > 0:

        # the largest contour is the best candidate for the moving object, this is the last item in the
        # contour vector
        largest_con = contours[-1]

        # set parameters for the bounding circle
        (x, y), radius = cv2.minEnclosingCircle(largest_con)
        center = (int(x), int(y))
        text_center = (int(x-125), int(y+100))

        # draw crosshair on image with text indicating the centroid of motion
        final_img = cv2.circle(bgr, center, 50, (0, 255, 0), 2)
        final_img = cv2.line(bgr, center, (int(x), int(y-75)), (0, 255, 0), 2)
        final_img = cv2.line(bgr, center, (int(x), int(y+75)), (0, 255, 0), 2)
        final_img = cv2.line(bgr, center, (int(x-75), int(y)), (0, 255, 0), 2)
        final_img = cv2.line(bgr, center, (int(x+75), int(y)), (0, 255, 0), 2)
        final_img = cv2.putText(bgr, "MOTION DETECTED: " + str(center), text_center, 1, 1, (0, 255, 0), 2)
        final_img = cv2.putText(bgr, str(now), (25, 25), 1, 1, (0, 255, 0), 2)

        alert_pub.publish("MOTION DETECTED: " + str(now))

        # show/publish motion image
        try:
            img = bridge.cv2_to_imgmsg(final_img, "bgr8")
            motion_pub.publish(img)
        except CvBridgeError, e:
            print e

    else:
        alert_pub.publish("ALL QUIET: " + str(now))
        final_img = cv2.putText(bgr, str(now), (25, 25), 1, 1, (0, 255, 0), 2)

    # return the image
    return final_img


# perform differential imaging
def get_diff_img(t0, t1, t2):
    d1 = cv2.absdiff(t2, t1)
    d2 = cv2.absdiff(t1, t0)
    return cv2.bitwise_and(d1, d2)


def motion_detector():
    global camera_img, image_sub, alert_pub, motion_pub, bridge, md_halted, md_ready

    threshold = 40
    blur = (10, 10)
    initialized = False

    rospy.init_node('motion_detector', anonymous=False)

    rospy.Subscriber("current_state", String, state_callback, queue_size=10)
    rospy.Subscriber("md_active", Bool, md_callback, queue_size=10)
    rospy.Subscriber("halt_motion_detection", Bool, halt_md_callback, queue_size=10)
    rospy.Subscriber("md_ready", Bool, md_ready_callback, queue_size=10)
    image_sub = rospy.Subscriber("/camera/rgb/image_color", Image, image_callback, queue_size=10)
    alert_pub = rospy.Publisher("/user_alerts", String, queue_size=10)
    motion_pub = rospy.Publisher("/motion_image", Image, queue_size=10)
    detection_pub = rospy.Publisher("/motion_detection_feed", Image, queue_size=10)

    rate = rospy.Rate(10)  # 120hz

    while not rospy.is_shutdown():

        if state == "Standby" or state == "Shutdown":
            initialized = False

        print "WAITING FOR NAVIGATION TO CEASE BEFORE PERFORMING MOTION DETECTION"

        if not md_halted and md_ready:
            print "NAVIGATION HAS CEASED - STARTING MOTION DETECTION PROCEDURES"

            if motion_detection is True and not initialized:
                print "INITIALIZING CAMERA"

                while camera_img is None:
                    print "Waiting for camera frames..."

                bgr_image = camera_img.copy()

                # grab 3 identical images to initialize
                t_minus = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
                t = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
                t_plus = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)

                initialized = True

            elif motion_detection is True and initialized:
                print "CAMERA INITIALIZED - PROCESSING IMAGES"

                # get differential image
                diff_img = get_diff_img(t_minus, t, t_plus)

                # perform thresholding and blurring
                na, thresh_img = cv2.threshold(diff_img, threshold, 255, cv2.THRESH_BINARY)
                blur_img = cv2.blur(thresh_img, blur)

                # perform thresholding again on blurred image
                na, blur_thresh_img = cv2.threshold(blur_img, threshold, 255, cv2.THRESH_BINARY)

                # create motion image
                detection_img = track_motion(blur_thresh_img, bgr_image)

                # show/publish motion image
                try:
                    img = bridge.cv2_to_imgmsg(detection_img, "bgr8")
                    detection_pub.publish(img)
                except CvBridgeError, e:
                    print e

                #cv2.imshow("MOTION TRACKING", detection_img)
                #cv2.waitKey(3)

                # DEBUG
                #cv2.imshow("BGR IMAGE", img)
                #cv2.imshow("DIFF IMAGE", diff_img)
                #cv2.imshow("THRESH IMAGE", thresh_img)
                #cv2.imshow("BLUR IMAGE", blur_img)
                #cv2.imshow("BLUR + THRESH IMAGE", blur_thresh_img)
                #cv2.waitKey(3)

                # retrieve a bgr image from the kinect
                image_sub = rospy.Subscriber("camera/rgb/image_color", Image, image_callback, queue_size=10)

                bgr_image = camera_img.copy()

                # increment the images
                t_minus = t
                t = t_plus
                t_plus = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)

        rate.sleep()

    rospy.spin()

if __name__ == '__main__':
    try:
        motion_detector()
    except rospy.ROSInterruptException:
        pass



