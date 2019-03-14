import akinaka_libs.cloudwatch
import akinaka_libs.costexplorer
import boto3
import time
import datetime
import sys
import tabulate

class BillingQueries():
    def __init__(self, region, assume_role_arn, days_ago):
        self.costexplorer = akinaka_libs.costexplorer.CostExplorer(region, assume_role_arn)
        self.days_ago = days_ago

    def print_x_days_estimates(self):
        try:
            response = self.costexplorer.get_bill_estimates(from_days_ago=self.days_ago)
            data = response['ResultsByTime']
        except Exception as e:
            print("Billing estimates is not available: {}".format(e))
            return e
        results = []
        if len(data) == 1:
            amount = float(data[0]['Total']['UnblendedCost']['Amount'])
            unit = data[0]['Total']['UnblendedCost']['Unit']
            date_today = datetime.datetime.now().strftime("%Y-%m-%d")
            results.append([date_today, "{} {:.2f}".format(unit, amount)])
            message = "\nToday's estimated bill\n"
        else:
            for d in data:
                unit = d['Total']['UnblendedCost']['Unit']
                amount = float(d['Total']['UnblendedCost']['Amount'])
                results.append([d['TimePeriod']['End'], "{} {:.2f}".format(unit, amount)])
            message = "\nEstimated bill for the past {} days\n".format(str(len(data)))
        message += tabulate.tabulate(results, headers=["Date", "Total"], tablefmt='psql')
        message += "\n"
        print(message)
        return message