import boto3
from akinaka_client.aws_client import AWS_Client
import akinaka_libs.helpers as helpers
from datetime import datetime, timezone

aws_client = AWS_Client()

class CloudWatch():
    def __init__(self, region, role_arn):
        self.cloudwatch_client = aws_client.create_client('cloudwatch', region, role_arn)

    def get_metric_statistics(self, namespace, name, seconds_ago=None, granularity=None, fields=None, stat_types=None, start=None, end=None):
        granularity = granularity or 120
        seconds_ago = seconds_ago or 86400
        start = start or helpers.datetime_this_seconds_ago(seconds_ago)
        end = end or datetime.now(timezone.utc)

        try:
            return self.cloudwatch_client.get_metric_statistics(
                Namespace = namespace,
                MetricName = name,  
                StartTime = start,
                EndTime = end,
                Period = granularity,
                Dimensions = fields,
                Statistics = stat_types
            )
        except Exception as e:
            return "Too many data points to return. Try adjusting either \"seconds_ago\" or \"granularity\\n{}".format(e)

    def get_bill_estimates(self, from_hours_ago=None):
        seconds_ago = None or helpers.seconds_from_hours(from_hours_ago)

        return self.get_metric_statistics(
            namespace = "AWS/Billing",
            name = "EstimatedCharges",
            seconds_ago = seconds_ago,
            granularity = 600,
            fields = [{ 'Name': 'Currency', 'Value': 'USD' }],
            stat_types = ["Maximum"],
        )['Datapoints']






