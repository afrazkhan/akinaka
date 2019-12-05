#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Scans services that may contain data, and returns a list with information on any storage found:

FIXME: EFS is currently out of scope, due to it not being treated as a native AWS service.
       i.e. There is no way to talk to objects stored in EFS outside of a VPC without peering.

[
    {
        "rds_arns": [
            "rds_arn_a",
            "rds_arn_b"
        ],
        "aurora_arns": [
            "rds_arn_a",
            "rds_arn_b"
        ],
        "s3_arns": [
            "s3_arn_a",
            "s3_arn_b"
        ]
    }
]
"""

import boto3
from akinaka.client.aws_client import AWS_Client

aws_client = AWS_Client()

class ScanResources():
    def __init__(self, region, role_arn):
        self.region = region
        self.role_arn = role_arn

    def scan_all(self):
        """ Scan all resource types in scope, and return separate lists for each """

        rds_arns = self.scan_rds()
        aurora_arns = self.scan_aurora()
        s3_arns = self.scan_s3()
        all_arns = { **rds_arns, **aurora_arns, **s3_arns }

        return all_arns

    def scan_rds(self):
        """ Return list of ARNs for all RDS objects """

        rds_client = aws_client.create_client('rds', self.region, self.role_arn)
        response = rds_client.describe_db_instances()['DBInstances']
        arns = [db['DBInstanceArn'] for db in response]

        return { 'rds_arns': arns }

    def scan_aurora(self):
        """ Return list of ARNs for all RDS Aurora objects """

        rds_client = aws_client.create_client('rds', self.region, self.role_arn)
        response = rds_client.describe_db_clusters()['DBClusters']
        arns = [db['DBClusterArn'] for db in response]

        return { 'aurora_arns': arns }

    def scan_s3(self):
        """ Return list of ARNs for all S3 buckets """

        s3_client = aws_client.create_client('s3', self.region, self.role_arn)
        names = [bucket['Name'] for bucket in s3_client.list_buckets()['Buckets']]
        arns = [ "arn:aws:s3:::" + name for name in names ]

        return { 's3_arns': arns }
