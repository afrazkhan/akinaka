#!/usr/bin/env python3

from kubernetes import client

class MonitorDeployment():

    def __init__(self, configuration, applications):

        client.Configuration.set_default(configuration)

        self.core_api = client.CoreV1Api()
        self.apps_api = client.AppsV1Api()


    # TODO:
    # kubectl --certificate-authority ca.crt --server $K8S_URL --token $K8S_TOKEN apply -f full_spec.yml
    def monitor_update(self):
        result = self.apps_api.read_namespaced_deployment(namespace="dispute", name="dispute")
        print(result)
