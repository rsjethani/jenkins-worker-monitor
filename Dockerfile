FROM dockerhub.cisco.com/iot-dockerpreprod/iot-alpine-images/iot-alpine-python3:3.4_3

WORKDIR /usr/src/app

COPY requirements.txt monitor.py ./

RUN pip install --no-cache-dir -r requirements.txt

CMD [ "python3", "./monitor.py" ]
