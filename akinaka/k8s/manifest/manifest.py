"""
Manipulations of Kubernetes manifest files
"""

#!/usr/bin/env python3

import yaml
import logging
from pathlib import Path
import sys
import re

class Manifest():
    """
    This is needed because kustomize ignores cronjobs :(

    It takes arguments to change the image field in all yaml files found at --directories for
    the containers specified by --containers
    """

    def __init__(self, dry_run, log_level):
        logging.getLogger().setLevel(log_level)
        self.dry_run = dry_run

    def update_image(self, new_image, new_tag, directories, containers):
        """ Update [image] in [] """

        file_paths = []
        for directory in directories:
            for path in Path(directory).glob('*.' + 'yaml'):
                file_paths.append(path)

        for file_path in file_paths:
            new_spec = yaml.dump_all(
                self.update_specs(file_path, new_image, new_tag, containers),
                default_flow_style=False,

            )

            if not self.dry_run:
                spec_file = open(file_path, "w")
                spec_file.write(new_spec)
                spec_file.close()
            else:
                print(new_spec)

    def read_specs(self, file_path):
        """
        Read the file at [file_path], and load it into a list of dict. It is a list
        because a file can have more than a single document

        This method will sys.exit(1) if it fails for any reason
        """

        yammies = []

        try:
            with open(file_path, 'r') as stream:
                try:
                    for yammy in yaml.safe_load_all(stream):
                        yammies.append(yammy)
                except yaml.YAMLError as exception:
                    logging.error(exception)
                    sys.exit(1)
            return yammies
        except Exception as exception:
            logging.error(exception)
            sys.exit(1)

    def update_specs(self, file_path, new_image, new_tag, containers):
        """
        Updates the specs found at in the file at [file_path] with new values for it's their
        ...spec.container.image fields. This method can handle the differences between cronjob
        specs and deployment specs. Other types are ignored with a warning, so it is safe to
        pass random files to it

        It returns all the specs back as an array
        """

        specs = self.read_specs(file_path)

        for spec in specs:
            if spec['kind'] == 'Deployment' or spec['kind'] == 'Pod':
                spec_path = spec['spec']['template']['spec']['containers']
            elif spec['kind'] == 'CronJob':
                spec_path = spec['spec']['jobTemplate']['spec']['template']['spec']['containers']
            else:
                logging.warning(f"Ignoring manifest with type '{spec['kind']}'") # pylint: disable=logging-fstring-interpolation
                continue

            for container in spec_path:
                if container['name'] in containers:
                    image_parts = self.split_image_url(container['image'])

                    image = new_image or image_parts['image']
                    tag = new_tag or image_parts['tag'] or 'latest'

                    container['image'] = f"{image_parts['repository']}/{image}:{tag}"
                else:
                    logging.info(f"Container {container['name']} didn't match, so skipping it") # pylint: disable=logging-fstring-interpolation

            # spec['metadata']['annotations']['kubernetes.io/change-cause'] = new_tag

        return specs

    def split_image_url(self, image):
        """
        Split the URL given as [image] into it's constituant parts and return:

          {
              'repository',
              'image',
              'tag'
          }

        This will work even if some parts such as port or tag are missing
        """

        matches = re.match( r'^(?P<name>(?:(?P<repository>(?:(?:localhost|[\w-]+(?:\.[\w-]+)+)(?::\d+)?)|[\w]+:\d+)/)?(?P<image>[a-z0-9_.-]+(?:/[a-z0-9_.-]+)*))(?::(?P<tag>[\w][\w.-]{0,127}))?(?:@(?P<digest>[A-Za-z][A-Za-z0-9]*(?:[+._-][A-Za-z][A-Za-z0-9]*)*:[0-9a-fA-F]{32,}))?$', image, re.M )
        return matches.groupdict()
