FROM python:3.7.3

ARG AKINAKA_VERSION

RUN pip install akinaka==${AKINAKA_VERSION}

ENTRYPOINT ["akinaka.py"]
