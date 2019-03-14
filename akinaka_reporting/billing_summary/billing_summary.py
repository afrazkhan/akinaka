import akinaka_libs.cloudwatch
import boto3
import time
import datetime
import sys

class BillingSummary():
    def __init__(self, region, source_role_arn):
        self.cloudwatch = akinaka_libs.cloudwatch.CloudWatch(region, source_role_arn)
