import click
from akinaka_libs import helpers
import logging

helpers.set_logger()

@click.group()
@click.option("--region", envvar='AWS_DEFAULT_REGION', help="Region your resources are located in")

@click.pass_context

# This is the Click() group that's imported into the CLI at the top level
def copy(ctx, region):
    ctx.obj = {'region': region}
    pass


@copy.command()
@click.pass_context
@click.option("--source-role-arn", required=True, help="Source role ARNs with assumable permissions")
@click.option("--target-role-arn", required=True, help="Destination role ARNs with assumable permissions")
@click.option("--snapshot-style", type=click.Choice(['running_instance', 'latest_snapshot']), required=True, help="Use latest available backup or create a new snapshot")
@click.option("--source-instance-name", required=True, help="RDS DB instance identifier")
@click.option("--target-instance-name", required=True, default=None, help="Name of the newly created RDS instance")
@click.option("--overwrite-target", is_flag=True, help="Specify this parameter to overwrite existing instance")
@click.option("--target-security-group", required=True, help="RDS Security to be attached to the target RDS instance")
@click.option("--target-db-subnet", required=True, help="RDS DB subnet to be attached to the instance")
def rds(ctx, source_role_arn, target_role_arn, snapshot_style, source_instance_name, overwrite_target, target_security_group, target_db_subnet, target_instance_name):
    from .copy import copy_rds
    region = ctx.obj.get('region')

    try:
        rds_copy = copy_rds.CopyRDS(region, source_role_arn, target_role_arn, snapshot_style, source_instance_name, overwrite_target, target_security_group, target_db_subnet, target_instance_name)
        rds_copy.copy_instance()
        exit(0)
    except Exception as e:
        logging.error(e)
        exit(1)
