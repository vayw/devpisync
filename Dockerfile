FROM python:alpine3.6

WORKDIR .
RUN mkdir /home/src/
COPY ./devpisync/ /home/src/devpisync/
COPY setup.py /home/src/
RUN pip install -r /home/src/devpisync/requirements.txt && pip install /home/src/

ENTRYPOINT ["python3", "/usr/local/bin/devpisync"]
