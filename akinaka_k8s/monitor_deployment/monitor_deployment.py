#!/usr/bin/env python3

from kubernetes import client

class MonitorDeployment():

    def __init__(self, configuration, applications):

        client.Configuration.set_default(configuration)

        self.api = client.CoreV1Api()


    def list_all(self):
        self.api.list_pod_for_all_namespaces(watch=False)
