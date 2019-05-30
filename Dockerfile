FROM python:3.7.3

RUN pip install akinaka

ENTRYPOINT ["akinaka.py"]
