"""
Manipulations of Kubernetes deployments
"""

#!/usr/bin/env python3

from kubernetes import client as k8s_client

class Deployment():
    """ TODO """

    def __init__(self, configuration):

        k8s_client.Configuration.set_default(configuration)

        self.core_api = k8s_client.CoreV1Api()
        self.apps_api = k8s_client.AppsV1Api()


    def monitor_update(self, namespace, deployment):
        """
        TODO
        Get the update status for [deployment] in [namespace]
        """

        result = self.apps_api.read_namespaced_deployment(namespace=namespace, name=deployment)
        print(result)
