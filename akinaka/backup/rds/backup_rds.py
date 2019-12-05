"""
TODO:

Encrypted manual snapshots that don't use the default RDS encryption key can be shared, but you must
first share the KMS key with the account that you want to share the snapshot with. To share the key
with another account, share the IAM policy with the primary and secondary accounts. Shared encrypted
snapshots can't be restored directly from the destination account. First, copy the snapshot to the
destination account by using a KMS key in the destination account.
"""

#!/usr/bin/env python3

import boto3
from akinaka.client.aws_client import AWS_Client
from akinaka.libs import helpers, kms_share
import logging

helpers.set_logger()
aws_client = AWS_Client()

class BackupRDS():
    def __init__(self, region, assumable_role_arn, live_account, backup_account):
        self.region = region
        self.assumable_role_arn = assumable_role_arn
        self.live_account = live_account
        self.backup_account = backup_account

    def backup(self, rds_arns):
        kms_sharer = kms_share.KMSShare(
            region = self.region,
            assumable_role_arn = self.assumable_role_arn,
            share_from_account = self.live_account,
            share_to_account = self.backup_account
        )

        shared_key = kms_sharer.get_kms_key(self.live_account)
