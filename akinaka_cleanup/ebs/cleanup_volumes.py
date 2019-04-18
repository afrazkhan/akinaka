#!/usr/bin/env python3

import boto3
import pprint
import datetime
from datetime import timedelta, timezone, datetime
from time import strftime
import dateutil.parser
from akinaka_client.aws_client import AWS_Client
from akinaka_libs import helpers
import logging

helpers.set_logger()
aws_client = AWS_Client()

class CleanupVolumes():

    def __init__(self, region, role_arns, not_dry_run):
          self.region = region
          self.role_arns = role_arns
          self.not_dry_run = not_dry_run

    def list_volumes(self, role_arn, filters={}):
        ec2_client = aws_client.create_client('ec2', self.region, role_arn)

        return ec2_client.describe_volumes(
            DryRun=False,
            Filters=[
                filters
            ],
            )['Volumes']

    def list_available_volumes(self, role_arn):
        return self.list_volumes(role_arn, filters={'Name': 'status', 'Values': ['available']})

    def delete_volumes(self, volumes, role_arn):
        ec2_client = aws_client.create_client('ec2', self.region, role_arn)
        volumes = self.list_available_volumes(role_arn)

        for volume in volumes:
            ec2_client.delete_volume(VolumeId=volume['VolumeId'])

    def cleanup(self):
        for role in self.role_arns:
            logging.error("\nProcessing account: {}".format(role))
            volumes_to_delete = self.list_available_volumes(role)

            if self.not_dry_run:
                logging.info("Deleting the following volumes and their snapshots: {}".format(volumes_to_delete))
                self.delete_volumes(volumes_to_delete, role)
            else:
                logging.info("These are the volumes I would have deleted if you gave me --not-dry-run:\n")
                for volume in volumes_to_delete:
                    logging.info("Volume: {}\n".format(volume['VolumeId']))



