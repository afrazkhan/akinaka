"""
Sharing snapshots between AWS accounts involves:

1. Creating a key to share between those two accounts, and sharing it
2. (Re)encrypting a snapshot from the live account with the shared key
3. Creating a key on the destination account
4. Copying and re-encrypting the copy to the destination account with that key

This module has all the methods needed to do that, and uses them in the entrypoint
method; transfer_snapshot()
"""

#!/usr/bin/env python3

from datetime import datetime
from operator import itemgetter
from akinaka.client.aws_client import AWS_Client
from akinaka.libs import helpers, exceptions
import logging
import time

helpers.set_logger()
aws_client = AWS_Client()

class TransferSnapshot():
    def __init__(
            self,
            region,
            source_role_arn,
            destination_role_arn,
            source_kms_key,
            destination_kms_key
        ):

        self.region = region
        self.source_role_arn = source_role_arn
        self.destination_role_arn = destination_role_arn
        self.source_kms_key = source_kms_key
        self.destination_kms_key = destination_kms_key

    def transfer_snapshot(self, take_snapshot, db_names, source_account, destination_account, keep, retention):
        """
        For every DB in [db_names], call methods to perform the actions listed in this module's
        docstring. Additionally, rotate the oldest snapshot out, if there are more than [retention]
        """

        for db_name in db_names:
            source_rds_client = aws_client.create_client('rds', self.region, self.source_role_arn, valid_for=14400)

            if take_snapshot:
                source_snapshot = self.take_snapshot(source_rds_client, db_name, self.source_kms_key)
                logging.info("Will now recrypt it with the shared key")
            else:
                source_snapshot = self.get_latest_snapshot(db_name)

            recrypted_snapshot = self.recrypt_snapshot(source_rds_client, source_snapshot, self.source_kms_key, source_account)

            self.share_snapshot(recrypted_snapshot, destination_account)

            logging.info('The snapshot must now be recrypted and copied with a key available only to the destination account')
            destination_rds_client = aws_client.create_client('rds', self.region, self.destination_role_arn, valid_for=14400)
            self.recrypt_snapshot(destination_rds_client, recrypted_snapshot, self.destination_kms_key, destination_account)

            self.rotate_snapshots(retention, db_name, keep=None)

    def rotate_snapshots(self, retention, db_name, keep):
        """
        Get all the snapshots for [db_name], and delete the oldest one if there are more than
        [retention] of them. Ignore any in the list [keep].

        Beware, this does not take distinct days into account, only the number of snapshots. So if you
        take more than [retention] snapshots in one day, all previous snapshots will be deleted
        """

        keep = keep or []

        destination_rds_client = aws_client.create_client('rds', self.region, self.destination_role_arn, valid_for=14400)

        snapshots = destination_rds_client.describe_db_snapshots(DBInstanceIdentifier=db_name)['DBSnapshots']
        if len(snapshots) > retention:
            oldest_snapshot = sorted(snapshots, key=itemgetter('SnapshotCreateTime'))[-1]

            if oldest_snapshot['DBSnapshotIdentifier'] not in keep:
                logging.info("There are more than the given retention number of snapshots in the account," \
                    "so we're going to delete the oldest: {}".format(oldest_snapshot['DBSnapshotIdentifier'])
                )

                destination_rds_client.delete_db_snapshot(
                    DBSnapshotIdentifier=oldest_snapshot['DBSnapshotIdentifier']
                )
            else:
                logging.info("Oldest snapshot ({}) is older than" \
                             "the retention period allows, but it's " \
                             "the --keep list so it will not be deleted".format(oldest_snapshot['DBSnapshotIdentifier']))

    def get_latest_snapshot(self, db_name):
        """
        Return the latest snapshot for [db_name], where the ARN can also be the name of the DB

        Note: You can only use the db_name if you are in the account with the DB in it, else you
              must use the DB name
        """

        source_rds_client = aws_client.create_client('rds', self.region, self.source_role_arn, valid_for=14400)
        # TODO: Yuk
        #       https://stackoverflow.com/questions/59285540/rewrite-python-method-depending-on-condition
        try:
            snapshots = source_rds_client.describe_db_snapshots(DBInstanceIdentifier=db_name)['DBSnapshots']
            latest = sorted(snapshots, key=itemgetter('SnapshotCreateTime'))[0]
            logging.info("Using snapshot {}".format(latest['DBSnapshotIdentifier']))
        except IndexError:
            snapshots = source_rds_client.describe_db_cluster_snapshots(DBClusterIdentifier=db_name)['DBClusterSnapshots']
            if len(snapshots) == 0:
                raise exceptions.AkinakaCriticalException("No snapshots found for {}. You'll need to take one first with --take-snapshot".format(db_name))
            latest = sorted(snapshots, key=itemgetter('SnapshotCreateTime'))[0]
            logging.info("Using snapshot {}".format(latest['DBClusterSnapshotIdentifier']))

        return latest

    def make_snapshot_name(self, db_name, account):
        """ Make a name based on [db_name] and [account] """

        date = datetime.utcnow().strftime('%Y%m%d-%H%M')

        return "{}-{}-{}".format(db_name, date, account)

    def recrypt_snapshot(self, rds_client, snapshot, kms_key, destination_account, tags=None):
        """
        Recrypt a snapshot [snapshot] with the KMS key [kms_key]. Return the recrypted snapshot.
        """

        # TODO: Yuk
        #       https://stackoverflow.com/questions/59285540/rewrite-python-method-depending-on-condition
        try:
            new_snapshot_id = self.make_snapshot_name(snapshot['DBInstanceIdentifier'], destination_account)

            try:
                recrypted_snapshot = rds_client.copy_db_snapshot(
                    SourceDBSnapshotIdentifier=snapshot['DBSnapshotArn'],
                    TargetDBSnapshotIdentifier=new_snapshot_id,
                    KmsKeyId=kms_key['KeyMetadata']['Arn'],
                    Tags=[ { 'Key': 'akinaka-made', 'Value': 'true' }, ] # FIXME: Add custom tags
                )

                self.wait_for_snapshot(recrypted_snapshot['DBSnapshot'], rds_client)

                logging.info("Recrypted snapshot {} with key {}".format(
                        recrypted_snapshot['DBSnapshot']['DBSnapshotIdentifier'],
                        kms_key['KeyMetadata']['Arn']
                    ))

                return recrypted_snapshot['DBSnapshot']
            except rds_client.exceptions.DBSnapshotAlreadyExistsFault:
                snapshots = rds_client.describe_db_snapshots(DBSnapshotIdentifier=new_snapshot_id)

                logging.info("Found existing snapshot {}".format(snapshots['DBSnapshots'][0]['DBSnapshotIdentifier']))
                return snapshots['DBSnapshots'][0]

        except KeyError:
            new_snapshot_id = self.make_snapshot_name(snapshot['DBClusterIdentifier'], destination_account)

            try:
                recrypted_snapshot = rds_client.copy_db_cluster_snapshot(
                    SourceDBClusterSnapshotIdentifier=snapshot['DBClusterSnapshotArn'],
                    TargetDBClusterSnapshotIdentifier=new_snapshot_id,
                    KmsKeyId=kms_key['KeyMetadata']['Arn'],
                    Tags=[ { 'Key': 'akinaka-made', 'Value': 'true' }, ] # FIXME: Add custom tags
                )

                self.wait_for_snapshot(recrypted_snapshot['DBClusterSnapshot'], rds_client)

                logging.info("Recrypted snapshot {} with key {}".format(
                        recrypted_snapshot['DBClusterSnapshot']['DBClusterSnapshotIdentifier'],
                        kms_key['KeyMetadata']['Arn']
                    ))

                return recrypted_snapshot['DBClusterSnapshot']
            except rds_client.exceptions.DBClusterSnapshotAlreadyExistsFault:
                snapshots = rds_client.describe_db_cluster_snapshots(DBClusterSnapshotIdentifier=new_snapshot_id)

                logging.info("Found existing snapshot {}".format(snapshots['DBClusterSnapshots'][0]['DBClusterSnapshotIdentifier']))
                return snapshots['DBClusterSnapshots'][0]


    def share_snapshot(self, snapshot, destination_account):
        """
        Share [snapshot] with [destination_account]
        """

        # TODO: Yuk
        #       https://stackoverflow.com/questions/59285540/rewrite-python-method-depending-on-condition
        try:
            source_rds_client = aws_client.create_client('rds', self.region, self.source_role_arn, valid_for=14400)
            source_rds_client.modify_db_snapshot_attribute(
                DBSnapshotIdentifier=snapshot['DBSnapshotIdentifier'],
                AttributeName='restore',
                ValuesToAdd=[destination_account]
            )

            logging.info("Recrypted snapshot {} has been shared with account {}".format(snapshot['DBSnapshotIdentifier'], destination_account))
        except KeyError:
            source_rds_client = aws_client.create_client('rds', self.region, self.source_role_arn, valid_for=14400)
            source_rds_client.modify_db_cluster_snapshot_attribute(
                DBClusterSnapshotIdentifier=snapshot['DBClusterSnapshotIdentifier'],
                AttributeName='restore',
                ValuesToAdd=[destination_account]
            )

            logging.info("Recrypted snapshot {} has been shared with account {}".format(snapshot['DBClusterSnapshotIdentifier'], destination_account))


    def wait_for_snapshot(self, snapshot, rds_client):
        """
        Check if [snapshot] is ready by querying it every 10 seconds
        """

        # TODO: Yuk
        #       https://stackoverflow.com/questions/59285540/rewrite-python-method-depending-on-condition
        try:
            while True:
                snapshotcheck = rds_client.describe_db_snapshots(
                    DBSnapshotIdentifier=snapshot['DBSnapshotIdentifier']
                )['DBSnapshots'][0]
                if snapshotcheck['Status'] == 'available':
                    logging.info("Snapshot {} has been created".format(snapshot['DBSnapshotIdentifier']))
                    break
                else:
                    logging.info("Snapshot {} is in progress; {}% complete".format(snapshot['DBSnapshotIdentifier'], snapshotcheck['PercentProgress']))
                    time.sleep(10)
        except KeyError:
            while True:
                snapshotcheck = rds_client.describe_db_cluster_snapshots(
                    DBClusterSnapshotIdentifier=snapshot['DBClusterSnapshotIdentifier']
                )['DBClusterSnapshots'][0]
                if snapshotcheck['Status'] == 'available':
                    logging.info("Snapshot {} has been created".format(snapshot['DBClusterSnapshotIdentifier']))
                    break
                else:
                    logging.info("Snapshot {} is in progress; {}% complete".format(snapshot['DBClusterSnapshotIdentifier'], snapshotcheck['PercentProgress']))
                    time.sleep(10)

    def take_snapshot(self, rds_client, db_name, kms_key):
        """
        Take a new snapshot of [db_name] using [kms_key]

        TODO: It's not possible to take a snapshot with a CMK, really?!
        """

        snapshot_name = self.make_snapshot_name(db_name, kms_key['KeyMetadata']['AWSAccountId'])

        try:
            snapshot = rds_client.create_db_snapshot(
                DBInstanceIdentifier=db_name,
                DBSnapshotIdentifier=snapshot_name,
                Tags=[ { 'Key': 'akinaka-made', 'Value': 'true' }, ]
            )

            self.wait_for_snapshot(snapshot['DBSnapshot'], rds_client)

            logging.info("Snapshot {} created".format(snapshot['DBSnapshot']['DBSnapshotIdentifier']))

            return snapshot['DBSnapshot']
        except rds_client.exceptions.DBInstanceNotFoundFault:
            snapshot = rds_client.create_db_cluster_snapshot(
                DBClusterIdentifier=db_name,
                DBClusterSnapshotIdentifier=snapshot_name,
                Tags=[ { 'Key': 'akinaka-made', 'Value': 'true' }, ]
            )

            self.wait_for_snapshot(snapshot['DBClusterSnapshot'], rds_client)

            logging.info("Snapshot {} created".format(snapshot['DBClusterSnapshot']['DBClusterSnapshotIdentifier']))

            return snapshot['DBClusterSnapshot']
