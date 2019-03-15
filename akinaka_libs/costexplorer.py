import boto3
from akinaka_client.aws_client import AWS_Client
import akinaka_libs.helpers as helpers
from datetime import datetime, timezone, timedelta

aws_client = AWS_Client()

class CostExplorer():
    def __init__(self, region, role_arn):
        self.costexplorer_client = aws_client.create_client('ce', region, role_arn)

    def get_bill_estimates(self, from_days_ago):
        days_ago = 0 or int(from_days_ago)
        
        if days_ago > 0:
            end = datetime.now().strftime("%Y-%m-%d")
            datetime_days_ago = datetime.now() - timedelta(days=days_ago + 1)
            start = datetime_days_ago.strftime("%Y-%m-%d")
        else:
            start = datetime.now().strftime("%Y-%m-%d")
            datetime_days_ago = datetime.now() + timedelta(days=1)
            end = datetime_days_ago.strftime("%Y-%m-%d")
        
        return self.costexplorer_client.get_cost_and_usage(
            TimePeriod={
                'Start': start,
                'End': end,
            },
            Granularity='DAILY',
            Metrics=[
                'UnblendedCost'
            ]
        )