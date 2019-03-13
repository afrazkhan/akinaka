#!/usr/bin/env python3

import boto3
from time import gmtime, strftime

class AWS_Client():

    def create_client(self, service, region, role_arn, valid_for=None):
        client_options = {
            'region_name': region
        }

        sts_client = boto3.client('sts', region_name=region)

        credentials = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName="gitlab-{}".format(strftime("%Y%m%d%H%M%S", gmtime())),
            DurationSeconds=valid_for or 900
        )

        client_options['aws_access_key_id'] = credentials['Credentials']['AccessKeyId']
        client_options['aws_secret_access_key'] = credentials['Credentials']['SecretAccessKey']
        client_options['aws_session_token'] = credentials['Credentials']['SessionToken']

        return boto3.client(service, **client_options)
