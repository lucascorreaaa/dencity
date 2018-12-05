import urllib.request
import cv2 as cv
import numpy as np

url = "http://192.168.15.12:8080/shot.jpg"

while True:
    imgResp = urllib.request.urlopen(url)
    imgNp = np.array(bytearray(imgResp.read()), dtype=np.uint8)
    img = cv.imdecode(imgNp, -1)
    cv.imshow("Cellphone camera", img)

    key = cv.waitKey(1)
    print(key)
    if key is not -1 : quit()