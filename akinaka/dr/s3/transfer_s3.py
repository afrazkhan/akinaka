"""
main() will:

1. Create a backup bucket in the backup account
2. Set lifecycle policies such that only [self.retention] number of versions are kept in the backup bucket
3. Set policies for the source bucket so that the backup account can get objects from it
4. Set policies for the backup bucket so that the backup account can use s3:PutBucketEncryption
5. Set an encryption policy to use [self.destination_kms_key]
6. Sync the source bucket to the backup bucket
"""

#!/usr/bin/env python3

from datetime import datetime
from akinaka.client.aws_client import AWS_Client
from akinaka.libs import helpers, exceptions
import logging

helpers.set_logger()
aws_client = AWS_Client()

class TransferS3():
    def __init__(
        self,
        region,
        source_role_arn,
        destination_role_arn,
        source_kms_key,
        destination_kms_key,
        retention):

        self.region = region
        self.source_role_arn = source_role_arn
        self.destination_role_arn = destination_role_arn
        self.source_kms_key = source_kms_key
        self.destination_kms_key = destination_kms_key
        self.retention = retention

    def main(self, old_bucket_names):
        """
        Go through all the actions in this module's docstring
        """

        for old_bucket_name in old_bucket_names:
            self.set_bucket_encryption(old_bucket_name, self.source_kms_key, self.source_role_arn)
            self.sync_bucket(old_bucket_name, old_bucket_name, self.source_kms_key, self.source_role_arn, self.source_role_arn)
            destination_account = self.account_id_from_role_arn(self.destination_role_arn)
            source_account = self.account_id_from_role_arn(self.source_role_arn)
            new_bucket_name = "{}-{}".format(old_bucket_name, destination_account)

            logging.info("Will create a backup bucket in the backup account if necessary")

            new_bucket_name = self.create_bucket(new_bucket_name, self.destination_role_arn)
            self.set_bucket_lifecycle(new_bucket_name, self.retention)
            self.set_bucket_policy(
                bucket=old_bucket_name,
                granter_role_arn=self.source_role_arn,
                grantee_account=destination_account
            )
            self.set_bucket_policy(
                bucket=new_bucket_name,
                granter_role_arn=self.destination_role_arn,
                grantee_account=source_account
            )
            self.set_bucket_encryption(new_bucket_name, self.destination_kms_key, self.destination_role_arn)
            self.sync_bucket(old_bucket_name, new_bucket_name, self.destination_kms_key, self.source_role_arn, self.destination_role_arn)

    def account_id_from_role_arn(self, role_arn):
        """
        Return the account ID that [role_arn] is attached to
        """

        sts_client = aws_client.create_client('sts', self.region, role_arn)
        return sts_client.get_caller_identity()['Account']

    def create_bucket(self, new_bucket_name, role_arn):
        """
        Create a bucket named [name]-backup to stored the backup objects in. Returns
        the name of the new bucket
        """

        destination_s3_client = aws_client.create_client('s3', self.region, role_arn)

        try:
            destination_s3_client.create_bucket(
                ACL='private',
                Bucket=new_bucket_name,
                CreateBucketConfiguration={
                    'LocationConstraint': self.region
                }
            )

            logging.info("Created the versioned bucket {}".format(new_bucket_name))
        except destination_s3_client.exceptions.BucketAlreadyExists:
            new_bucket_name = new_bucket_name + "-x"

            logging.info("Bucket name was taken (probably because you're trying to restore " \
                "the same account multiple times?), so the new bucket name " \
                "is going to become: {}".format(new_bucket_name))

            self.create_bucket(new_bucket_name, role_arn)
        except destination_s3_client.exceptions.BucketAlreadyOwnedByYou:
            logging.info("No need to create {}, as it already exists and we own it".format(new_bucket_name))

        destination_s3_client.put_bucket_versioning(
            Bucket=new_bucket_name,
            VersioningConfiguration= {
                'Status': 'Enabled'
            }
        )
        logging.info("Successfully applied versioning to the bucket")

        return new_bucket_name

    def set_bucket_lifecycle(self, name, retention):
        """
        Set the lifecycle policy for the versioned objects in bucket [name] to [retention] days
        """

        destination_s3_client = aws_client.create_client('s3', self.region, self.destination_role_arn)

        destination_s3_client.put_bucket_lifecycle_configuration(
            Bucket=name,
            LifecycleConfiguration={
                'Rules': [
                    {
                        'ID': 'Akinaka',
                        'Prefix': '',
                        'Status': 'Enabled',
                        'NoncurrentVersionExpiration': {
                            'NoncurrentDays': retention
                        }
                    },
                ]
            }
        )

        logging.info("Set a lifecycle policy to keep only {} " \
            "versions of objects, for the destination bucket".format(retention))

    def set_bucket_policy(self, bucket, granter_role_arn, grantee_account):
        """
        Set a policy on [bucket] such that the account of [granter_role_arn] can perform
        get, list, and put operations.

        Uses [granter_role_arn] to make the call, since
        that is the only account which already has access to make this kind of change on
        a bucket policy
        """

        source_s3_client = aws_client.create_client('s3', self.region, granter_role_arn)

        source_s3_client.put_bucket_policy(
            Bucket=bucket,
            ConfirmRemoveSelfBucketAccess=True,
            Policy="""{
                "Id": "Policy1576178812268",
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "Stmt1576178805544",
                        "Action": "*",
                        "Effect": "Allow",
                        "Resource": "arn:aws:s3:::%s/*",
                        "Principal": {
                            "AWS": [
                            "arn:aws:iam::%s:root"
                            ]
                        }
                    }
                ]
            }""" % (bucket, grantee_account)
        )

        logging.info('Successfully set a bucket policy so that account {} '\
            'can perform operations on bucket {}'.format(grantee_account, bucket))

    def set_bucket_encryption(self, bucket, kms_key, role_arn):
        """
        Set the encryption options on [bucket] to be enabled and use [kms_key]. Uses [role_arn]
        to create a client to perform the operation
        """

        s3_client = aws_client.create_client('s3', self.region, role_arn)

        s3_client.put_bucket_encryption(
            Bucket=bucket,
            ServerSideEncryptionConfiguration={
                'Rules': [
                    {
                        'ApplyServerSideEncryptionByDefault': {
                            'SSEAlgorithm': 'aws:kms',
                            'KMSMasterKeyID': kms_key['KeyMetadata']['KeyId']
                        }
                    },
                ]
            }
        )

        logging.info("Successfully set encryption on the bucket")

    def sync_bucket(self, source_bucket, destination_bucket, kms_key, source_role_arn, destination_role_arn):
        """
        Sync objects from [source_bucket] to [destination_bucket], ensuring all objects
        are encrypted with [kms_key].

        The passing of [source_role_arn] and [destination_role_arn] is so that we can (ab)use
        this method as a recryptor for when we need to restore from a backup account
        """

        source_s3_client = aws_client.create_client('s3', self.region, source_role_arn)
        destination_s3_client = aws_client.create_client('s3', self.region, destination_role_arn)

        try:
            source_objects = source_s3_client.list_objects(Bucket=source_bucket)['Contents']
        except KeyError:
            logging.error("Failed to get a listing for objects for the bucket, " \
                "probably because there were no objects to sync")
            return

        for obj in source_objects:
            copy_source = {
                'Bucket': source_bucket,
                'Key': obj['Key']
            }

            destination_s3_client.copy_object(
                ACL='private',
                Bucket=destination_bucket,
                CopySource=copy_source,
                Key=obj['Key'],
                ServerSideEncryption='aws:kms',
                SSEKMSKeyId=kms_key['KeyMetadata']['KeyId'],
            )

            logging.info("Synced object {}".format(obj['Key']))
