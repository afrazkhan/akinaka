#!/usr/bin/env python

from akinaka_client.aws_client import AWS_Client
import boto3
import time
import datetime
import sys
from akinaka_libs import helpers
import logging

helpers.set_logger()
aws_client = AWS_Client()

class CopyRDS():
    def __init__(self, region, source_role_arn, target_role_arn, snapshot_style, source_instance_name, overwrite_target, target_security_group, target_db_subnet, target_instance_name):
        self.region = region
        self.source_role_arn = source_role_arn
        self.target_role_arn = target_role_arn
        self.snapshot_style = snapshot_style
        self.source_instance_name = source_instance_name
        self.overwrite_target = overwrite_target
        self.target_security_group = target_security_group
        self.target_db_subnet = target_db_subnet
        self.target_instance_name = target_instance_name

    def copy_instance(self):
        logging.info("Starting RDS copy...")
        rds_source_client   = aws_client.create_client('rds', self.region, self.source_role_arn, 5400)
        rds_target_client   = aws_client.create_client('rds', self.region, self.target_role_arn, 5400)
        kms_client          = aws_client.create_client('kms', self.region, self.source_role_arn, 5400)
        source_account      = aws_client.create_client('sts', self.region, self.source_role_arn, 5400).get_caller_identity()['Account']
        target_account      = aws_client.create_client('sts', self.region, self.target_role_arn, 5400).get_caller_identity()['Account']
        target_account_arn  = aws_client.create_client('sts', self.region, self.source_role_arn, 5400).get_caller_identity()['Arn'].split('/boto')[0].replace(':sts::', ':iam::', 1).replace('assumed-role', 'role', 1)

        kms_key = self.get_kms_key(kms_client, source_account, target_account, target_account_arn)

        # Automated Amazon RDS snapshots cannot be shared with other AWS accounts.
        # To share an automated snapshot, copy the snapshot to make a manual version,
        # and then share the copy.
        # Additionally the copy needs to be re-encrypted with the Customer Managed KMS key
        if self.snapshot_style == 'running_instance':
            snapshot = self.make_snapshot_from_running_instance(rds_source_client, self.source_instance_name)
            self.wait_for_snapshot_to_be_ready(rds_source_client, snapshot)
        elif self.snapshot_style == 'latest_snapshot':
            # get latest snapshot from an AWS account with a given tag
            snapshot = self.get_latest_automatic_rds_snapshots(rds_source_client, self.source_instance_name)
        else:
            raise ValueError('snapshot_style has to be running_instance or latest_snapshot, but value {} found'.format(self.snapshot_style))

        recrypted_copy = self.recrypt_snapshot_with_new_key(rds_source_client, snapshot, kms_key)
        self.wait_for_snapshot_to_be_ready(rds_source_client, recrypted_copy)
        self.share_snapshot_with_external_account(rds_source_client, recrypted_copy, target_account)

        # an encrypted shared snapshot owned by another account cannot be restored straight up
        # so make a local copy in the target environment first
        target_copy = self.copy_shared_snapshot_to_local(rds_target_client, recrypted_copy, kms_key)

        self.wait_for_snapshot_to_be_ready(rds_target_client, target_copy)
        self.rename_or_delete_target_instance(rds_target_client, self.target_instance_name, self.overwrite_target)

        target_instance = self.create_rds_instance_from_snapshot(rds_client=rds_target_client,
                                                            snapshot=target_copy,
                                                            instancename=self.target_instance_name,
                                                            dbsubnet_group=self.target_db_subnet)

        self.wait_for_instance_to_be_ready(rds_target_client, target_instance)

        self.modify_rds_instance_security_groups(rds_client=rds_target_client, instancename=self.target_instance_name, securitygroup=self.target_security_group)

        logging.info("Finished, check instance {}!".format(self.target_instance_name))

    def get_kms_key(self, kms_client, source_account, target_account, target_account_arn):

        key_alias = 'alias/RDSBackupRestoreSharedKeyWith{}'.format(target_account)
        logging.info("Searching for Customer Managed KMS Key with alias {} that is already shared with account {}...".format(key_alias, target_account))

        # try to retrieve the KMS key with the specified alias to see if it exists
        try:
            key = kms_client.describe_key(KeyId=key_alias)
            logging.info("Found key: {}".format(key['KeyMetadata']['Arn']))
            return key
        except kms_client.exceptions.NotFoundException:
            # if it doesn't exist, create it
            logging.error("No valid key found.")
            key = self.create_shared_kms_key(kms_client, source_account, target_account, target_account_arn, key_alias)
            return key

    def create_shared_kms_key(self, kms_client, source_account, target_account, target_account_arn, key_alias):

        logging.info("Creating Customer Managed KMS Key that is shared...")

        # create a Customer Managed KMS key, needed to be able to share the encrypted snapshot
        kms_key = kms_client.create_key(
            Description="Shared encryption key with AWS account {}".format(target_account_arn),
            Policy="""{
        "Version": "2012-10-17",
        "Id": "key-default-1",
        "Statement": [
            {
                "Sid": "Enable IAM User Permissions",
                "Effect": "Allow",
                "Principal": {
                    "AWS": "arn:aws:iam::%s:root"
                },
                "Action": "kms:*",
                "Resource": "*"
            },
            {
                "Sid": "Allow use of the key by the %s",
                "Effect": "Allow",
                "Principal": {
                    "AWS": "%s"
                },
                "Action": "kms:*",
                "Resource": "*"
            }
        ]
    }
    """ % (source_account, target_account, target_account_arn)
        )

        # add an alias to the key so we can later more easily determine if the key
        # already exists without having to know it's keyid
        kms_client.create_alias(
            AliasName=key_alias,
            TargetKeyId=kms_key['KeyMetadata']['Arn']
        )

        logging.info("Created KMS Key {}, shared with account {}".format(kms_key['KeyMetadata']['Arn'], target_account_arn))
        return kms_key

    def copy_shared_snapshot_to_local(self, rds_client, shared_snapshot, kms_key):
        # unfortunately it's not possible to restore an RDS instance directly from a
        # snapshot that is shared by another account. This makes a copy local to the
        # account where we want to restore the RDS instance
        target_db_snapshot_id = "{}-copy".format(shared_snapshot['DBSnapshotIdentifier'])

        logging.info("Copying shared snaphot {} to local snapshot {}...".format(shared_snapshot['DBSnapshotArn'], target_db_snapshot_id))

        try:
            copy = rds_client.copy_db_snapshot(
                SourceDBSnapshotIdentifier=shared_snapshot['DBSnapshotArn'],
                TargetDBSnapshotIdentifier=target_db_snapshot_id,
                KmsKeyId=kms_key['KeyMetadata']['Arn']
            )
            logging.info("Copy created.")
            return copy['DBSnapshot']
        except rds_client.exceptions.DBSnapshotAlreadyExistsFault:
            # if the snapshot we tried to make already exists, retrieve it
            logging.info("Snapshot already exists, retrieving {}...".format(target_db_snapshot_id))

            snapshots = rds_client.describe_db_snapshots(
                DBSnapshotIdentifier=target_db_snapshot_id,
            )
            logging.info("Retrieved.")
            return snapshots['DBSnapshots'][0]

    def share_snapshot_with_external_account(self, rds_client, snapshot, target_account):
        # in order to restore a snapshot from another account it needs to be shared
        # with that account first
        logging.info("Modifying snaphot {} to be shared with account {}...".format(snapshot['DBSnapshotArn'], target_account))
        rds_client.modify_db_snapshot_attribute(
            DBSnapshotIdentifier=snapshot['DBSnapshotIdentifier'],
            AttributeName='restore',
            ValuesToAdd=[target_account]
        )
        logging.info("Modified.")

    def rename_or_delete_target_instance(self, rds_client, instancename, overwrite_target ):
        logging.info("Checking for an existing RDS instance by the name {} and renaming or deleting if it's found".format(instancename))
        # check if we already have an instance by this name
        try:
            instance = rds_client.describe_db_instances(DBInstanceIdentifier=instancename)['DBInstances'][0]
            logging.info("Instance found")
        except rds_client.exceptions.DBInstanceNotFoundFault:
            instance = None
            logging.info("Instance not found")

        if instance is not None:
            if overwrite_target:
                logging.info("Instance found and overwrite if found True, deleting instance")
                rds_client.delete_db_instance(
                    DBInstanceIdentifier=instancename,
                    SkipFinalSnapshot=True
                    )
                logging.info("Deleting instance. This will take a while...")
                waiter = rds_client.get_waiter('db_instance_deleted')
                waiter.wait(
                    DBInstanceIdentifier=instancename,
                    WaiterConfig={
                        'MaxAttempts': 120
                    }
                )
                logging.info("Instance is deleted!")
            else:
                logging.info("Instance found and renaming instance")
                try:
                    rds_client.modify_db_instance(
                        DBInstanceIdentifier=instancename,
                        NewDBInstanceIdentifier="{}-old".format(instancename),
                        ApplyImmediately=True
                    )
                except:
                    raise

    def wait_for_instance_to_be_ready(self, rds_client, instance):
        # simply check if the specified instance is healthy every 5 seconds until it
        # is
        while True:
            instancecheck = rds_client.describe_db_instances(DBInstanceIdentifier=instance['DBInstance']['DBInstanceIdentifier'])['DBInstances'][0]
            if instancecheck['DBInstanceStatus'] == 'available':
                logging.info("Instance {} ready and available!".format(instance['DBInstance']['DBInstanceIdentifier']))
                break
            else:
                logging.info("Instance creation in progress, sleeping 10 seconds...")
                time.sleep(10)

    def wait_for_snapshot_to_be_ready(self, rds_client, snapshot):
        # simply check if the specified snapshot is healthy every 5 seconds until it
        # is
        while True:
            snapshotcheck = rds_client.describe_db_snapshots(DBSnapshotIdentifier=snapshot['DBSnapshotIdentifier'])['DBSnapshots'][0]
            if snapshotcheck['Status'] == 'available':
                logging.info("Snapshot {} complete and available!".format(snapshot['DBSnapshotIdentifier']))
                break
            else:
                logging.info("Snapshot {} in progress, {}% complete".format(snapshot['DBSnapshotIdentifier'], snapshotcheck['PercentProgress']))
                time.sleep(10)

    def make_snapshot_from_running_instance(self, rds_client, source_instance_name):
        logging.info("Making a new snapshot from the running RDS instance")
        try:
            today = datetime.date.today()
            snapshot = rds_client.create_db_snapshot(
                DBInstanceIdentifier=source_instance_name,
                DBSnapshotIdentifier="{}-{:%Y-%m-%d}".format(source_instance_name, today),
            )
            logging.info("Snapshot created.")
            return snapshot['DBSnapshot']
        except Exception as exception:
            logging.error("Failed to make snapshot from instance: {}".format(exception))
            sys.exit(1)

    def get_latest_automatic_rds_snapshots(self, rds_client, source_instance_name):
        logging.info("Getting latest (automated) snapshot from rds instance {}...".format(source_instance_name))
        # we can't query for the latest snapshot straight away, so we have to retrieve
        # a full list and go through all of them
        snapshots = rds_client.describe_db_snapshots(
            DBInstanceIdentifier=source_instance_name,
            SnapshotType='automated'
        )

        latest = 0
        for snapshot in snapshots['DBSnapshots']:
            if latest == 0:
                latest = snapshot
            if snapshot['SnapshotCreateTime'] > latest['SnapshotCreateTime']:
                latest = snapshot

        logging.info("Found snapshot {}".format(latest['DBSnapshotIdentifier']))
        return latest

    def recrypt_snapshot_with_new_key(self, rds_client, snapshot, kms_key):
        # create an identifier to use as the name of the manual snapshot copy
        if ':' in snapshot['DBSnapshotIdentifier']:
            target_db_snapshot_id = "{}-recrypted".format(snapshot['DBSnapshotIdentifier'].split(':')[1])
        else:
            target_db_snapshot_id = "{}-recrypted".format(snapshot['DBSnapshotIdentifier'])

        logging.info("Copying automatic snapshot to manual snapshot...")

        try:
            # copy the snapshot, supplying the new KMS key (which is also shared with
            # the target account)
            copy = rds_client.copy_db_snapshot(
                SourceDBSnapshotIdentifier=snapshot['DBSnapshotIdentifier'],
                TargetDBSnapshotIdentifier=target_db_snapshot_id,
                KmsKeyId=kms_key['KeyMetadata']['Arn']
            )
            logging.info("Snapshot created.")
            return copy['DBSnapshot']
        except rds_client.exceptions.DBSnapshotAlreadyExistsFault:
            # if the snapshot we tried to make already exists, retrieve it
            logging.info("Snapshot already exists, retrieving {}".format(target_db_snapshot_id))

            snapshots = rds_client.describe_db_snapshots(
                DBSnapshotIdentifier=target_db_snapshot_id,
            )

            return snapshots['DBSnapshots'][0]

    def create_rds_instance_from_snapshot(self, rds_client, snapshot, instancename, dbsubnet_group):
        # restore an instance from the specified snapshot
        logging.info("Restoring RDS instance {} from snapshot {}".format(instancename, snapshot['DBSnapshotIdentifier']))
        try:
            if dbsubnet_group is None:
                dbsubnet_group = 'default'

            instance = rds_client.restore_db_instance_from_db_snapshot(
                DBInstanceIdentifier=instancename,
                DBSnapshotIdentifier=snapshot['DBSnapshotArn'],
                DBSubnetGroupName=dbsubnet_group,
            )
            logging.info("RDS instance restored.")
            return instance
        except rds_client.exceptions.DBInstanceAlreadyExistsFault:
            logging.error("An instance with the name {} already exists, please specify a different name or remove that instance first".format(instancename))
            sys.exit(1)

    def modify_rds_instance_security_groups(self, rds_client, instancename, securitygroup):
        logging.info("Modifying RDS instance to attach correct securitygroup")
        try:
            rds_client.modify_db_instance(
                DBInstanceIdentifier=instancename,
                VpcSecurityGroupIds=[
                    securitygroup
                ],
                ApplyImmediately=True
            )
            logging.info("RDS Instance {} modified".format(instancename))
        except Exception as e:
            logging.error("{}".format(e))
            raise
