import click

@click.group()
@click.option("--region", required=True, help="Region your resources are located in")

@click.pass_context

def rds(ctx, region, source_role_arn, target_role_arn):
    ctx.obj = {'region': region}
    pass


@copy.command()
@click.pass_context
@click.option("--source-role-arn", required=True, help="Source role ARNs with assumable permissions")
@click.option("--target-role-arn", required=True, help="Destination role ARNs with assumable permissions")
@click.option("--snapshot_style", type=click.Choice(['running_instance', 'latest_snapshot']), required=True, help="Use latest available backup or create a new snapshot")
@click.option("--db_id", required=True, help="RDS DB instance identifier")
@click.option("--overwrite_target", is_flag=True, help="Specify this parameter to overwrite existing instance")
@click.option("--security_group", required=True, help="RDS Security to be attached to the target RDS instance")
@click.option("--db_subnet", required=True, help="RDS DB subnet to be attached to the instance")
@click.option("--target_instance_name", default=None, help="Name of the newly created RDS instance")

def copy(ctx, source_role_arn, target_role_arn, snapshot_style, db_id, overwrite_target, security_group, db_subnet, target_instance_name):
    from .copy import copy_rds
    region = ctx.obj.get('region')

    try:
        rds_copy = copy_rds.CopyRDS(region, source_role_arn, target_role_arn, snapshot_style, db_id, overwrite_target, security_group, db_subnet, target_instance_name)
        rds_copy.copy_instance()
        exit(0)
    except Exception as e:
        print(e)
        exit(1)
