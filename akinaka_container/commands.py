import click

# This is the Click() group that's imported into the CLI at the top level
@click.group()
@click.option("--region", required=True, help="Region your resources are located in. N.B. Currently, only us-east-1 supports estimates")
@click.option("--role-arn", required=True, help="Role ARN which contains necessary assume permissions")
@click.pass_context
def container(ctx, region, role_arn):
    ctx.obj = {'region': region, 'role_arn': role_arn}
    pass


@container.command(name="get-ecr-login")
@click.pass_context
@click.option("--registry", required=True, help="Registry you want to retrieve a docker login auth for")
def bill_estimates(ctx, registry):
    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')

    from .ecr import ecr_login
    ecr_login.ECRLogin(region, role_arn).get_login(registry)
