#!/usr/bin/env python3

from time import sleep
from akinaka_libs import helpers
from akinaka_libs import exceptions
import yaml
import logging

class UpdateDeployment():
    """Modify a Kubernetes YAML deployment spec"""

    def __init__(self, applications, new_image=None, new_tag=None, file_paths=None, dry_run=False):
        self.applications = [x.strip() for x in applications.split(',')]
        self.new_image = new_image
        self.new_tag = new_tag
        self.file_paths = [x.strip() for x in file_paths.split(',')]
        self.dry_run = dry_run

        if not self.new_image and not self.new_tag:
            logging.error("At least --new-image or --new-tag need to be given")
            exit(1)

    def read_specs(self, file_path):
        yammies = []

        try:
            with open(file_path, 'r') as stream:
                try:
                    for yammy in yaml.safe_load_all(stream):
                        yammies.append(yammy)
                except yaml.YAMLError as exception:
                    logging.error(exception)
                    exit(1)

            return yammies
        except Exception as exception:
            logging.error(exception)
            exit(1)

    def update_spec(self, file_path):
        specs = self.read_specs(file_path)

        for spec in specs:
            if spec['kind'] == 'Deployment' or spec['kind'] == 'Pod':
                spec_path = spec['spec']['template']['spec']['containers']
            elif spec['kind'] == 'CronJob':
                spec_path = spec['spec']['jobTemplate']['spec']['template']['spec']['containers']
            else:
                logging.error("Can't handle spec file type of {}".format(spec['kind']))
                exit(1)

            for container in spec_path:
                if container['name'] in self.applications:
                    if self.new_image:
                        image = self.new_image
                    else:
                        image = container['image'].split(":")[0]

                    if self.new_tag:
                        tag = self.new_tag
                    else:
                        tag = container['image'].split(":")[-1]

                    container['image'] = "{image}:{tag}".format(image = image, tag = tag)
                else:
                    logging.warning("Didn't find every container searched for from the array {}, and didn't change any files".format(self.applications))

            # spec['metadata']['annotations']['kubernetes.io/change-cause'] = self.new_tag


        return specs

    def write_new_spec(self):
        for file_path in self.file_paths:

            new_spec = yaml.dump_all(self.update_spec(file_path), default_flow_style=False)

            if not self.dry_run:
                spec_file = open(file_path, "w")
                spec_file.write(new_spec)
                spec_file.close()
            else:
                print(new_spec)
