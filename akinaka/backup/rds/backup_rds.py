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
from akinaka.libs import helpers
import logging

helpers.set_logger()
aws_client = AWS_Client()

class BackupRDS():
    def __init__(self, region, role_arn):
        self.region = region
        self.role_arn = role_arn

    def backup(self, rds_arns):
        """
        1. Create KMS key in source account
        1. Share KMS key with destination account (caller — this account)
        1.
        1. Create snapshot with this KMS key
        1. Share KMS key with destination account
        """
        print(rds_arns)
