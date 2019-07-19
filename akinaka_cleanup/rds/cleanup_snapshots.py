#!/usr/bin/env python3

import boto3
from akinaka_client.aws_client import AWS_Client
from akinaka_libs import helpers
import logging

helpers.set_logger()
aws_client = AWS_Client()

class CleanupSnapshots():

    def __init__(self, region, role_arns, search_tags, not_dry_run):
          self.region = region
          self.role_arns = role_arns.split(",")
          self.search_tags = search_tags.split(",")
          self.not_dry_run = not_dry_run

    def list_tagged_snapshots(self, role_arn, search_tags):
        rds_client = aws_client.create_client('rds', self.region, role_arn)

        snapshots = rds_client.describe_db_snapshots()['DBSnapshots']

        found_list = []
        for snapshot in snapshots:
            snapshot_arn = snapshot['DBSnapshotArn']
            snapshot_id = snapshot['DBSnapshotIdentifier']

            tags = rds_client.list_tags_for_resource(
                ResourceName=snapshot_arn
            )['TagList']

            for tag in tags:
                if [ snapshot_id for search_tag in search_tags if tag['Key'] == search_tag ] != []:
                    found_list.append(snapshot_id)

        return found_list

    def delete_snapshots(self, role_arn, snapshots_to_delete):
        rds_client = aws_client.create_client('rds', self.region, role_arn)

        for snapshot in snapshots_to_delete:
            try:
                logging.info(rds_client.delete_db_snapshot(DBSnapshotIdentifier=snapshot))
            except rds_client.exceptions.InvalidDBSnapshotStateFault as e:
                logging.error(
                    "Snapshot is not deletable, probably an automated snapshot:\n"
                    "{}".format(e)
                )

    def cleanup(self):
        for role in self.role_arns:
            logging.info("Processing account: {}".format(role))
            snapshots_to_delete = self.list_tagged_snapshots(role, self.search_tags)

            if self.not_dry_run:
                logging.info("Deleting the following snapshots: {}".format(snapshots_to_delete))
                self.delete_snapshots(role, snapshots_to_delete)
            else:
                logging.info("These are the snapshots I would have deleted if you gave me --not-dry-run: {}".format(snapshots_to_delete))
