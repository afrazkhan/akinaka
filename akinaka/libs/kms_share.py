#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Create shared KMS keys for use in encrypting and decrypting the same objects in different accounts.

Terminology used below:

share_from_account = The account to create the key in, where the resources to be encrypted are
share_to_account = The account you're calling this from
assumable_role_arn = Role in share_from_account that permits STS assume from share_to_account
"""

import boto3
from akinaka.libs import helpers
import logging
from akinaka.client.aws_client import AWS_Client

aws_client = AWS_Client()
helpers.set_logger()

class KMSShare():
    def __init__(self, region, assumable_role_arn, share_from_account, share_to_account):
        self.region = region
        self.assumable_role_arn = assumable_role_arn
        self.share_from_account = share_from_account
        self.share_to_account = share_to_account
        self.share_to_account_arn = "arn:aws:iam::{}:root".format(share_to_account)

    def get_kms_key(self, share_from_account):
        """
        Check to see if there is already a shared key. The name (alias) to check will be:
        alias/RDSBackupRestoreSharedKeyWith[(account id of)share_to_account]. If there is no shared key,
        call create_shared_key() to make one.

        In both cases, return the ID of a shared KMS key
        """

        live_kms_client = aws_client.create_client('kms', self.region, self.assumable_role_arn)

        key_alias = 'alias/SharedKeyWithAccount{}'.format(self.share_to_account)
        logging.info("Searching for Customer Managed KMS Key with alias {} that is already shared with account {}".format(key_alias, self.share_to_account))

        try:
            key = live_kms_client.describe_key(KeyId=key_alias)
            logging.info("Found key: {}".format(key['KeyMetadata']['Arn']))

            return key
        except live_kms_client.exceptions.NotFoundException:
            logging.info("No valid key found")
            key = self.create_shared_key(share_from_account, key_alias)

            return key

    def create_shared_key(self, share_from_account, key_alias):
        """
        Create new KMS key in share_from_account, with a policy that shares it
        to share_to_account (the account you're calling this from)
        """

        logging.info("Creating a shared KMS key")

        live_kms_client = aws_client.create_client('kms', self.region, self.assumable_role_arn)

        key_policy = """{
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
                                    "Sid": "Allow use of the key by the %s account",
                                    "Effect": "Allow",
                                    "Principal": {
                                        "AWS": "%s"
                                    },
                                    "Action": "kms:*",
                                    "Resource": "*"
                                }
                            ]
                        }""" % (self.share_from_account, self.share_to_account, self.share_to_account_arn)

        kms_key = live_kms_client.create_key(
            Description="Shared encryption key with AWS account {}".format(self.share_to_account),
            Policy=key_policy)

        live_kms_client.create_alias(
            AliasName=key_alias,
            TargetKeyId=kms_key['KeyMetadata']['Arn']
        )

        logging.info("Created KMS Key {}, shared with account {}".format(kms_key['KeyMetadata']['Arn'], self.share_to_account))

        return kms_key
