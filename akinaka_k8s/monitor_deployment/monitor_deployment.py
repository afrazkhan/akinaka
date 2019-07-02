#!/usr/bin/env python3

from kubernetes import client

class MonitorDeployment():

    def __init__(self, configuration, applications):

        client.Configuration.set_default(configuration)

        self.api = client.CoreV1Api()


    # TODO:
    # kubectl --certificate-authority ca.crt --server $K8S_URL --token $K8S_TOKEN apply -f full_spec.yml
    def deploy_update(self):
        self.api.list_pod_for_all_namespaces(watch=False)
