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

class CleanupAMIs():

    def __init__(self, region, role_arns, retention, not_dry_run, exceptional_amis=None, launch_templates=None):
          self.region = region
          self.role_arns = role_arns
          self.retention = int(retention)
          self.exceptional_amis = exceptional_amis
          self.launch_templates = launch_templates
          self.retention_end = (datetime.now(timezone.utc) + timedelta(days=-self.retention))
          self.not_dry_run = not_dry_run

    def list_amis(self, filters={}, ids=[]):
        ec2_client = aws_client.create_client('ec2', self.region, self.role_arns[0])
        sts_client = aws_client.create_client('sts', self.region, self.role_arns[0])
        account_id = sts_client.get_caller_identity().get('Account')

        return ec2_client.describe_images(
            Owners=[ account_id ],
            DryRun=False,
            Filters=[
                filters
            ],
            ImageIds=ids
            )['Images']

    def delist_out_of_retention_amis(self, all_amis):
        amis_to_delete = set()
        
        for ami in all_amis:
            if dateutil.parser.parse(ami['CreationDate']) < self.retention_end:
                amis_to_delete.add(ami['ImageId'])

        # Same with list comprehension
        # logging.info([ami for ami in all_amis if dateutil.parser.parse(ami['CreationDate']) < self.retention_start])
        return amis_to_delete

    def delist_in_use_amis(self, amis):
        unused_amis = set()
        all_accounts_instances = []
        instance_amis = set()
              
        for role in self.role_arns:
            ec2_client = aws_client.create_client('ec2', self.region, role)
            all_accounts_instances.append(ec2_client.describe_instances()['Reservations'])

        all_accounts_instances = [account for accounts in all_accounts_instances for account in accounts]
        for account_instance in all_accounts_instances:
            instance_amis.add(account_instance['Instances'][0]['ImageId'])        

        for ami in amis:
            if ami in instance_amis:
                continue
            unused_amis.add(ami)
            
        return unused_amis
                  
    def delist_latest_arbitrary_amis(self, amis):      
        for exceptional_ami in self.exceptional_amis:

            filter = {
                'Name': 'name',
                'Values': [ exceptional_ami ]
            }

            all_arbitrary_amis = self.list_amis(filter)            
            amis.discard(max(all_arbitrary_amis, key=lambda x:x['CreationDate'])['ImageId'])
        
        return amis

    def delist_launch_template_finds(self, amis):
        ec2_client = aws_client.create_client('ec2', self.region, self.role_arns[0])

        for launch_template in self.launch_templates:
            latest_version = ec2_client.describe_launch_templates(
                LaunchTemplateNames=[launch_template]
            )['LaunchTemplates'][0]['LatestVersionNumber']
            str(latest_version)
            
            # It shouldn't be possible to have no value for ImageId, but it is :D
            try:
                in_use_ami = ec2_client.describe_launch_template_versions(
                    LaunchTemplateName=launch_template,
                    Versions=[latest_version]
                )['LaunchTemplateVersions'][0]['LaunchTemplateData']['ImageId']
            except:
                in_use_ami = ""

            amis.discard(in_use_ami)
        
        return amis

    def get_snapshot(self, ami):
        return self.list_amis(ids=[ami])[0]['BlockDeviceMappings'][0]['Ebs']['SnapshotId']

    def delete_amis(self, amis):
        ec2_client = aws_client.create_client('ec2', self.region, self.role_arns[0])

        for ami in amis:
            snapshot = self.get_snapshot(ami)        
            ec2_client.deregister_image(ImageId=ami)
            ec2_client.delete_snapshot(SnapshotId=snapshot)

    def cleanup(self):
        amis_to_delete = self.delist_out_of_retention_amis(self.list_amis())
        amis_to_delete = self.delist_in_use_amis(amis_to_delete)
        amis_to_delete = self.delist_latest_arbitrary_amis(amis_to_delete)
        amis_to_delete = self.delist_launch_template_finds(amis_to_delete)
        
        if self.not_dry_run:
            logging.info("Deleting the following AMIs and their snapshots: {}".format(amis_to_delete))
            self.delete_amis(amis_to_delete)
        else:
            logging.info("These are the AMIs I would have deleted if you gave me --not-dry-run: {}".format(amis_to_delete))



