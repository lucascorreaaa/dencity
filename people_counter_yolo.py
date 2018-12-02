""" DENCITY """
# USAGE
# To read and write back out to video:
# python people_counter_yolo.py -w yolo/yolov3.weights -m yolo/wolov3.cfg \ 
# -i videos/<video-name>.<video-extension> -o output/<video-name>.<video-extension>
#
# To read from webcam and write back out to disk you just need to specify no input argument.

# import the necessary packages
from pyimagesearch.centroidtracker import CentroidTracker
from pyimagesearch.trackableobject import TrackableObject
from imutils.video import VideoStream
from imutils.video import FPS
import numpy as np
import argparse
import imutils
import time
import cv2 as cv
import dlib

# Get the names of the output layers
def getOutputsNames(net):
    # Get the names of all the layers in the network
    layersNames = net.getLayerNames()
    # Get the names of the output layers, i.e. the layers with unconnected outputs
    return [layersNames[i[0] - 1] for i in net.getUnconnectedOutLayers()]

# Draw the predicted bounding box
def drawPred(classId, conf, left, top, right, bottom):
    # Draw a bounding box.
    cv.rectangle(frame, (left, top), (right, bottom), (255, 178, 50), 3)
    
    label = '%.2f' % conf
        
    # Get the label for the class name and its confidence
    if classes:
        assert(classId < len(classes))
        label = '%s:%s' % (classes[classId], label)

    #Display the label at the top of the bounding box
    labelSize, baseLine = cv.getTextSize(label, cv.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    top = max(top, labelSize[1])
    cv.rectangle(frame, (left, top - round(1.5*labelSize[1])), (left + round(1.5*labelSize[0]), top + baseLine), (255, 255, 255), cv.FILLED)
    cv.putText(frame, label, (left, top), cv.FONT_HERSHEY_SIMPLEX, 0.75, (0,0,0), 1)

# construct the argument parse and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("-w", "--weights", required=True,
	help="path to Yolo 'deploy' weights file")
ap.add_argument("-m", "--model", required=True,
	help="path to Yolo pre-trained model")
ap.add_argument("-i", "--input", type=str,
	help="path to optional input video file")
ap.add_argument("-o", "--output", type=str,
	help="path to optional output video file")
ap.add_argument("-c", "--confidence", type=float, default=0.5,
	help="minimum probability to filter weak outs")
ap.add_argument("-s", "--skip-frames", type=int, default=20,
	help="# of skip frames between outs")
args = vars(ap.parse_args())

# Load names of classes
classesFile = "yolo/coco.names"
classes = None
with open(classesFile, 'rt') as f:
    classes = f.read().rstrip('\n').split('\n')

# load our serialized model from disk
print("[INFO] loading model...")
net = cv.dnn.readNetFromDarknet(args["model"], args["weights"])
net.setPreferableBackend(cv.dnn.DNN_BACKEND_OPENCV)
net.setPreferableTarget(cv.dnn.DNN_TARGET_CPU)

# if a video path was not supplied, grab a reference to the webcam
if not args.get("input", False):
	print("[INFO] starting video stream...")
	vs = VideoStream(src=0).start()
	time.sleep(2.0)

# otherwise, grab a reference to the video file
else:
	print("[INFO] opening video file...")
	vs = cv.VideoCapture(args["input"])

# initialize the video writer (we'll instantiate later if need be)
writer = None

# initialize the frame dimensions (we'll set them as soon as we read
# the first frame from the video)
W = None
H = None

# Initialize the parameters
confThreshold = args["confidence"]  #Confidence threshold
nmsThreshold = 0.4   #Non-maximum suppression threshold

# instantiate our centroid tracker, then initialize a list to store
# each of our dlib correlation trackers, followed by a dictionary to
# map each unique object ID to a TrackableObject
ct = CentroidTracker(maxDisappeared=40, maxDistance=50)
trackers = []
trackableObjects = {}

# initialize the total number of frames processed thus far, along
# with the total number of objects that have moved either up or down
totalFrames = 0
totalDown = 0
totalUp = 0

# start the frames per second throughput estimator
fps = FPS().start()

# loop over frames from the video stream
while True:
	# grab the next frame and handle if we are reading from either
	# VideoCapture or VideoStream
	frame = vs.read()
	frame = frame[1] if args.get("input", False) else frame

	# if we are viewing a video and we did not grab a frame then we
	# have reached the end of the video
	if args["input"] is not None and frame is None:
		break

	# resize the frame to have a maximum width of 500 pixels (the less data we have, the faster we can process it), then 
	# convert the frame from BGR to RGB for dlib
	#frame = imutils.resize(frame, width=416, height=416)								-->> SE DESCOMENTAR, NÃO GERA O VIDEO DE OUTPUT
	rgb = cv.cvtColor(frame, cv.COLOR_BGR2RGB)

	# if the frame dimensions are empty, set them
	if W is None or H is None:
		W = 640 #frame.shape[1] // 2
		H = 350 #frame.shape[0] // 2

	# if we are supposed to be writing a video to disk, initialize
	# the writer
	if args["output"] is not None and writer is None:
		fourcc = cv.VideoWriter_fourcc('M','J','P','G')
		writer = cv.VideoWriter(args["output"], fourcc, 30, (round(vs.get(cv.CAP_PROP_FRAME_WIDTH)), round(vs.get(cv.CAP_PROP_FRAME_HEIGHT))))

	# initialize the current status along with our list of bounding
	# box rectangles returned by either (1) our object detector or
	# (2) the correlation trackers
	status = "Waiting"
	rects = []

	# check to see if we should run a more computationally expensive
	# object detection method to aid our tracker
	if totalFrames % args["skip_frames"] == 0:
		# set the status and initialize our new set of object trackers
		status = "Detecting"
		trackers = []

		# convert the frame to a blob and pass the blob through the
		# network and obtain the outs
		blob = cv.dnn.blobFromImage(frame, 1/255, (W, H), [0,0,0], 1, crop=False)
		net.setInput(blob)
		outs = net.forward(getOutputsNames(net))
		#frameHeight = frame.shape[0]
		#frameWidth = frame.shape[1]

		# Scan through all the bounding boxes output from the network and keep only the
		# ones with high confidence scores. Assign the box's class label as the class with the highest score.
		classIds = []
		confidences = []
		boxes = []
		for out in outs:
			for detection in out:
				scores = detection[5:]
				classId = np.argmax(scores)
				confidence = scores[classId]

				if confidence > confThreshold:
					# if the class label is not a person, ignore it
					if classes[classId] != "person":
						continue
					center_x = int(detection[0] * W) # centroid x-axis value
					center_y = int(detection[1] * H) # centroid y-axis value
					width = int(detection[2] * W)
					height = int(detection[3] * H)
					left = int(center_x - width / 2)
					top = int(center_y - height / 2)
					classIds.append(classId)
					confidences.append(float(confidence))
					cv.putText(frame, "left-top", (left - 10, top - 10), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
					cv.circle(frame, (left, top), 4, (0, 0, 255), -1)
					boxes.append([left, top, width, height])

		# Perform non maximum suppression to eliminate redundant overlapping boxes with
		# lower confidences.
		indices = cv.dnn.NMSBoxes(boxes, confidences, confThreshold, nmsThreshold)
		for i in indices:
			i = i[0]
			box = boxes[i]
			left = box[0]
			top = box[1]
			width = box[2]
			height = box[3]
			drawPred(classIds[i], confidences[i], left, top, left + width, top + height)

			# DEBUG - cv.putText(frame, "left-top", (left - 10, top - 10), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
			# DEBUG - cv.circle(frame, (left, top), 4, (0, 0, 255), -1)
			# DEBUG - cv.putText(frame, "left+width & top+height", ((left + width) - 10, (top + height) - 10), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
			# DEBUG - cv.circle(frame, ((left + width), (top + height)), 4, (0, 0, 255), -1)

			# add the bounding box coordinates to the rectangles list
			rects.append((left, top, left + width, top + height))

			# construct a dlib rectangle object from the bounding
			# box coordinates and then start the dlib correlation
			# tracker
			tracker = dlib.correlation_tracker()
			rect = dlib.rectangle(left, top, left + width, top + height)
			tracker.start_track(rgb, rect)

			# add the tracker to our list of trackers so we can
			# utilize it during skip frames
			trackers.append(tracker)

	# otherwise, we should utilize our object *trackers* rather than
	# object *detectors* to obtain a higher frame processing throughput
	else:
		# loop over the trackers
		for tracker in trackers:
			# set the status of our system to be 'tracking' rather
			# than 'waiting' or 'detecting'
			status = "Tracking"

			# update the tracker and grab the updated position
			tracker.update(rgb)
			pos = tracker.get_position()

			# unpack the position object
			startX = int(pos.left())
			startY = int(pos.top())
			endX = int(pos.right())
			endY = int(pos.bottom())
			# DEBUG - cv.putText(frame, "left-top", (startX - 10, startY - 10), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
			# DEBUG - cv.circle(frame, (startX, startY), 4, (0, 0, 255), -1)
			# DEBUG - cv.putText(frame, "bottom-right", (endX - 10, endY - 10), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
			# DEBUG - cv.circle(frame, (endX, endY), 4, (0, 0, 255), -1)
			# DEBUG - cX = int((startX + endX) / 2.0)
			# DEBUG - cY = int((startY + endY) / 2.0)
			# DEBUG - cv.putText(frame, "center", (cX - 10, cY - 10), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
			# DEBUG - cv.circle(frame, (cX, cY), 4, (0, 0, 255), -1)

			# add the bounding box coordinates to the rectangles list
			rects.append((startX, startY, endX, endY))

	# draw a horizontal line in the center of the frame -- once an
	# object crosses this line we will determine whether they were
	# moving 'up' or 'down'
	cv.line(frame, (0, H // 2), (W, H // 2), (0, 255, 255), 2)

	# use the centroid tracker to associate the (1) old object
	# centroids with (2) the newly computed object centroids
	objects = ct.update(rects)

	# loop over the tracked objects
	for (objectID, centroid) in objects.items():
		# check to see if a trackable object exists for the current
		# object ID
		to = trackableObjects.get(objectID, None)

		# if there is no existing trackable object, create one
		if to is None:
			to = TrackableObject(objectID, centroid)

		# otherwise, there is a trackable object so we can utilize it
		# to determine direction
		else:
			# the difference between the y-coordinate of the *current*
			# centroid and the mean of *previous* centroids will tell
			# us in which direction the object is moving (negative for
			# 'up' and positive for 'down')
			y = [c[1] for c in to.centroids]
			direction = centroid[1] - np.mean(y)
			to.centroids.append(centroid)

			# check to see if the object has been counted or not
			if not to.counted:
				# if the direction is negative (indicating the object
				# is moving up) AND the centroid is above the center
				# line, count the object
				if direction < 0 and centroid[1] < H // 2:
					# print("CENTROID UP! - Frame: {} ".format(totalFrames))
					totalUp += 1
					to.counted = True

				# if the direction is positive (indicating the object
				# is moving down) AND the centroid is below the
				# center line, count the object
				elif direction > 0 and centroid[1] > H // 2:
					# print("CENTROID DOWN! - Frame: {} ".format(totalFrames))
					totalDown += 1
					to.counted = True

		# store the trackable object in our dictionary
		trackableObjects[objectID] = to

		# draw both the ID of the object and the centroid of the
		# object on the output frame
		text = "ID {}".format(objectID)
		cv.putText(frame, text, (centroid[0] - 10, centroid[1] - 10),
		cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
		cv.circle(frame, (centroid[0], centroid[1]), 4, (0, 255, 0), -1)

	# construct a tuple of information we will be displaying on the
	# frame
	info = [
		("Up", totalUp),
		("Down", totalDown),
		("Status", status),
		("Frame", totalFrames),
	]

	# loop over the info tuples and draw them on our frame
	for (i, (k, v)) in enumerate(info):
		text = "{}: {}".format(k, v)
		cv.putText(frame, text, (10, H - ((i * 20) + 20)),
		cv.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

	# check to see if we should write the frame to disk
	if writer is not None:
		#writer.write(frame.astype(np.uint8))
		writer.write(frame)

	# show the output frame
	cv.imshow("Frame", frame)
	key = cv.waitKey(1) & 0xFF

	# if the `q` key was pressed, break from the loop
	if key == ord("q"):
		break

	# increment the total number of frames processed thus far and
	# then update the FPS counter
	totalFrames += 1
	fps.update()

# stop the timer and display FPS information
fps.stop()
print("[INFO] elapsed time: {:.2f}".format(fps.elapsed()))
print("[INFO] approx. FPS: {:.2f}".format(fps.fps()))

# check to see if we need to release the video writer pointer
if writer is not None:
	writer.release()

# if we are not using a video file, stop the camera video stream
if not args.get("input", False):
	vs.stop()

# otherwise, release the video file pointer
else:
	vs.release()

# close any open windows
cv.destroyAllWindows()