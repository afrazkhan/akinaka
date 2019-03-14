import akinaka_libs.cloudwatch
import boto3
import time
import datetime
import sys

class BillingQueries():
    def __init__(self, region, assume_role_arn):
        self.cloudwatch = akinaka_libs.cloudwatch.CloudWatch(region, assume_role_arn)

    def print_last_two_estimates(self):
        estimates = self.cloudwatch.get_bill_estimates(from_hours_ago=72)
        sorted_estimates = sorted(estimates, key=lambda k: k['Timestamp'])

        print("Last estimate     ({}): {}".format(sorted_estimates[-1]['Timestamp'], sorted_estimates[-1]['Maximum']))
        print("Previous estimate ({}): {}".format(sorted_estimates[-2]['Timestamp'], sorted_estimates[-2]['Maximum']))
