FROM python:3.5-alpine

WORKDIR /usr/src/app

COPY requirements.txt monitor.py ./

RUN pip install --no-cache-dir -r requirements.txt

CMD [ "python", "./monitor.py" ]
