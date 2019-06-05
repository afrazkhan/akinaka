#!/usr/bin/env python3

from time import sleep
from akinaka_libs import helpers
from akinaka_libs import exceptions
import yaml
import logging

class UpdateDeployment():
    """Modify a Kubernetes YAML deployment spec"""

    def __init__(self, application, new_image=None, new_tag=None, file_path=None):
        self.application = application
        self.new_image = new_image
        self.new_tag = new_tag
        self.file_path = file_path

        if not self.new_image and not self.new_tag:
            logging.error("At least --new-image or --new-tag need to be given")
            exit(1)

    def read_spec(self):
        try:
            with open(self.file_path, 'r') as stream:
                try:
                    return yaml.safe_load(stream)
                except yaml.YAMLError as exception:
                    logging.error(exception)
                    exit(1)
        except Exception as exception:
            logging.error(exception)
            exit(1)

    def update_spec(self):
        spec = self.read_spec()

        for container in spec['spec']['template']['spec']['containers']:
            if container['name'] == self.application:
                if self.new_image:
                    image = self.new_image
                else:
                    image = container['image'].split(":")[0]

                if self.new_tag:
                    tag = self.new_tag
                else:
                    tag = container['image'].split(":")[-1]

                container['image'] = "{image}:{tag}".format(image = image, tag = tag)

        return spec

    def write_new_spec(self):
        new_spec = self.update_spec()
        spec_file = open(self.file_path, "w")
        spec_file.write(yaml.dump(new_spec, default_flow_style=False))
        spec_file.close()
