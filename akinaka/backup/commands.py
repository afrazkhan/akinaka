import click
from akinaka.client.aws_client import AWS_Client
from akinaka.libs import helpers, scan_resources_storage
from time import gmtime, strftime
import logging
import pprint

@click.group()
@click.option("--region", required=True, help="Region your resources are located in")
@click.option("--role-arn", required=True, help="Role ARN which contains necessary assume permissions")
@click.option("--dry-run", is_flag=True, help="Don't back anything up, just list would be backed up")
@click.pass_context
def backup(ctx, region, role_arn, dry_run):
    """
    Backup subcommand. Does nothing by itself except pass the global options through to it's
    subcommands via ctx
    """

    ctx.obj = {
        'region': region,
        'role_arn': role_arn,
        'dry_run': dry_run,
        'log_level': ctx.obj.get('log_level')
    }

    pass

@backup.command()
@click.pass_context
def backup_all(ctx):
    """ Backup all data in any found instances of RDS, Aurora, and S3  """

    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')
    dry_run = ctx.obj.get('dry_run')

    scanner = scan_resources_storage.ScanResources(region, role_arn)
    scanner.scan_all()

    if dry_run:
        exit(0)

    # from .backup_all import backup_backup_all
    # backup_all = backup_backup_all.backup_all(region=region, role_arn=role_arn)

@backup.command()
@click.pass_context
def aurora(ctx):
    """ Backup all aurora clusters found """

    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')
    dry_run = ctx.obj.get('dry_run')

    scanner = scan_resources_storage.ScanResources(region, role_arn)
    scanner.scan_aurora()

    if dry_run:
        exit(0)

    # from .aurora import backup_aurora
    # aurora = backup_aurora.aurora(region=region, role_arn=role_arn)

@backup.command()
@click.pass_context
def rds(ctx):
    """ Backup all RDS instances found """

    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')
    dry_run = ctx.obj.get('dry_run')

    scanner = scan_resources_storage.ScanResources(region, role_arn)
    rds_arns = scanner.scan_rds()

    print("Will attempt to backup the following RDS instances, unless this is a dry run:")
    pprint.pprint(rds_arns)

    if dry_run:
        exit(0)

    from .rds import backup_rds
    rds = backup_rds.BackupRDS(region=region, role_arn=role_arn)
    rds.backup(rds_arns=rds_arns)

@backup.command()
@click.pass_context
def s3(ctx):
    """ Backup all s3 buckets found """

    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')
    dry_run = ctx.obj.get('dry_run')

    scanner = scan_resources_storage.ScanResources(region, role_arn)
    scanner.scan_s3()

    if dry_run:
        exit(0)

    # from .s3 import backup_s3
    # s3 = backup_s3.s3(region=region, role_arn=role_arn)
