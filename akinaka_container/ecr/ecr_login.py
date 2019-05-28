import boto3
from akinaka_client.aws_client import AWS_Client
from akinaka_libs import helpers
import base64
import logging

helpers.set_logger()
aws_client = AWS_Client()

class ECRLogin():
    def __init__(self, region, assume_role_arn):
        self.region = region
        self.assume_role_arn = assume_role_arn

    def get_login(self, registry):
        ecr_client = aws_client.create_client('ecr', self.region, self.assume_role_arn)

        token = ecr_client.get_authorization_token(registryIds=[registry])['authorizationData'][0]['authorizationToken']
        decoded_token = base64.standard_b64decode(token).decode('utf-8')
        username = decoded_token.split(":")[0]
        password = decoded_token.split(":")[1]

        login_string = "docker login -u {username} -p {password} https://{registry}.dkr.ecr.{region}.amazonaws.com".format(
            username=username,
            password=password,
            registry=registry,
            region=self.region
        )

        print(login_string)
