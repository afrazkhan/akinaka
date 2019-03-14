import click

# This is the Click() group that's imported into the CLI at the top level
@click.group()
@click.option("--region", required=True, help="Region your resources are located in. N.B. Currently, only us-east-1 supports estimates")
@click.option("--role-arn", required=True, help="Role ARN which contains necessary assume permissions")
@click.pass_context
def billing(ctx, region, role_arn):
    ctx.obj = {'region': region, 'role_arn': role_arn}
    pass


@billing.command()
@click.pass_context
def estimate(ctx):
    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')

    from .billing_summary import billing_queries
    billing_queries.BillingQueries(region, role_arn).print_last_two_estimates()
    
