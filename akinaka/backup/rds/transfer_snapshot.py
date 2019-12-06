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
from akinaka.libs import helpers, kms_share
import logging
import time

helpers.set_logger()
aws_client = AWS_Client()

class TransferSnapshot():
    def __init__(
        self,
        region,
        source_role_arn,
        destination_role_arn
        ):

        self.region = region
        self.source_role_arn = source_role_arn
        self.destination_role_arn = destination_role_arn

        source_sts_client = aws_client.create_client('sts', self.region, self.source_role_arn)
        self.source_account = source_sts_client.get_caller_identity()['Account']

        destination_sts_client = aws_client.create_client('sts', self.region, self.destination_role_arn)
        self.destination_account = destination_sts_client.get_caller_identity()['Account']


    def get_shared_kms_key(self):
        """
        Create and return shared KMS account between [self.source_account] and [self.destination_account]
        """

        kms_sharer = kms_share.KMSShare(
            region = self.region,
            assumable_role_arn = self.source_role_arn,
            share_from_account = self.source_account,
            share_to_account = self.destination_account
        )

        return kms_sharer.get_kms_key(self.source_account)

    def create_local_kms_key(self):
        """
        Search for a key name that should exists if this has been run before. If not found,
        create it. In both cases, return the key.
        """

        destination_kms_client = aws_client.create_client('kms', self.region, self.destination_role_arn)
        key_alias = "alias/{}".format(self.source_account)

        try:
            kms_key = destination_kms_client.describe_key(KeyId=key_alias)
            logging.info("Found key: {}".format(kms_key['KeyMetadata']['Arn']))
        except destination_kms_client.exceptions.NotFoundException:
            kms_key = destination_kms_client.create_key()
            logging.info("No existing key found, so we created one: {}".format(kms_key['KeyMetadata']['Arn']))

            destination_kms_client.create_alias(
                AliasName=key_alias,
                TargetKeyId=kms_key['KeyMetadata']['Arn']
            )

        return kms_key

    def transfer_snapshot(self, take_snapshot, db_arns, source_kms_key):
        """
        For every DB in [db_arns], call methods to:

        1. Either take a new snapshot (TODO), or use the latest automatically created one
        2. Recrypt the snapshot with [source_kms_key]. This key must be shared between accounts
        3. Share it with self.destination_account
        4. Copy it to self.destination_account with the [destination_kms_key]
        """

        for arn in db_arns:
            if take_snapshot:
                source_snapshot = self.take_snapshot(arn, source_kms_key)
            else:
                source_snapshot = self.get_latest_snapshot(arn)

            source_rds_client = aws_client.create_client('rds', self.region, self.source_role_arn)
            recrypted_snapshot = self.recrypt_snapshot(source_rds_client, source_snapshot, source_kms_key)

            self.share_snapshot(recrypted_snapshot, self.destination_account)

            destination_rds_client = aws_client.create_client('rds', self.region, self.destination_role_arn)
            self.recrypt_snapshot(destination_rds_client, recrypted_snapshot, self.create_local_kms_key())

    def get_latest_snapshot(self, db_arn):
        """
        Return the latest snapshot for [db_arn], where the ARN can also be the name of the DB

        Note: You can only use the db_arn if you are in the account with the DB in it, else you
              must use the DB name
        """

        source_rds_client = aws_client.create_client('rds', self.region, self.source_role_arn)
        snapshots = source_rds_client.describe_db_snapshots(DBInstanceIdentifier=db_arn)['DBSnapshots']

        try:
            latest = sorted(snapshots, key=itemgetter('SnapshotCreateTime'))[0]
        except KeyError:
            logging.error("Couldn't get the latest snapshot, probably because it's still being made")

        logging.info("Found automatic snapshot {}".format(latest['DBSnapshotIdentifier']))

        return latest

    def make_snapshot_name(self, db_name):
        date = datetime.utcnow().strftime('%Y%m%d-%H%M')

        return "{}-{}-{}".format(db_name, date, self.destination_account)

    def recrypt_snapshot(self, rds_client, snapshot, kms_key, tags=None):
        """
        Recrypt a snapshot [snapshot] with the KMS key [kms_key]. Return the recrypted snapshot.
        """

        new_snapshot_id = self.make_snapshot_name(snapshot['DBInstanceIdentifier'])

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

    def share_snapshot(self, snapshot, destination_account):
        """
        Share [snapshot] with [destination_account]
        """

        source_rds_client = aws_client.create_client('rds', self.region, self.source_role_arn)
        source_rds_client.modify_db_snapshot_attribute(
            DBSnapshotIdentifier=snapshot['DBSnapshotIdentifier'],
            AttributeName='restore',
            ValuesToAdd=[destination_account]
        )

        logging.info("Recrypted snapshot {} has been shared with account {}".format(snapshot['DBSnapshotIdentifier'], destination_account))

    def wait_for_snapshot(self, snapshot, rds_client):
        """
        Check if [snapshot] is ready by querying it every 10 seconds
        """

        while True:
            snapshotcheck = rds_client.describe_db_snapshots(
                DBSnapshotIdentifier=snapshot['DBSnapshotIdentifier']
            )['DBSnapshots'][0]
            if snapshotcheck['Status'] == 'available':
                logging.info("Snapshot {} complete and available!".format(snapshot['DBSnapshotIdentifier']))
                break
            else:
                logging.info("Snapshot {} in progress, {}% complete".format(snapshot['DBSnapshotIdentifier'], snapshotcheck['PercentProgress']))
                time.sleep(10)

    def take_snapshot(self, db_name, source_kms_key):
        """
        TODO: Take a new snapshot of [db_name] using [source_kms_key]. If we're here, we don't need to
              recrypt, since we already have a shared key to begin with. Some of the logic in
              transfer_snapshot() will need to be changed to accommodate this once ready
        """
        return "TODO"
