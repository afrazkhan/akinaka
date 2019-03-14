import akinaka_libs.cloudwatch
import boto3
import time
import datetime
import sys

class BillingQueries():
    def __init__(self, region, assume_role_arn):
        self.cloudwatch = akinaka_libs.cloudwatch.CloudWatch(region, assume_role_arn)

    def print_last_two_estimates(self):
        try:
            estimates = self.cloudwatch.get_bill_estimates(from_hours_ago=72)
            sorted_estimates = sorted(estimates, key=lambda k: k['Timestamp'])
        except Exception as e:
            print("Couldn't get last two estimates: {}".format(e))
        
        message = """\
Last estimate     ({}): {}
Previous estimate ({}): {}
""".format(sorted_estimates[-1]['Timestamp'], sorted_estimates[-1]['Maximum'], sorted_estimates[-2]['Timestamp'], sorted_estimates[-2]['Maximum'])

        print(message)
        return message