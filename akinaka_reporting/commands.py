import click

# This is the Click() group that's imported into the CLI at the top level
@click.group()
@click.option("--region", required=True, help="Region your resources are located in. N.B. Currently, only us-east-1 supports estimates")
@click.option("--role-arn", required=True, help="Role ARN which contains necessary assume permissions")
@click.pass_context
def reporting(ctx, region, role_arn):
    ctx.obj = {'region': region, 'role_arn': role_arn}
    pass


@reporting.command(name="bill-estimates")
@click.pass_context
@click.option("--from-days-ago", "from_days_ago", default=0, help="Number of days ago.")
def bill_estimates(ctx, from_days_ago):
    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')

    from .billing_summary import billing_queries
    billing_queries.BillingQueries(region, role_arn).days_estimates(from_days_ago)
    
    
