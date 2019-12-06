import click
from akinaka.client.aws_client import AWS_Client
from akinaka.libs import helpers, scan_resources_storage
from time import gmtime, strftime
import logging
import pprint
import boto3

helpers.set_logger()

@click.group()
@click.option("--region", required=True, help="Region your resources are located in")
@click.option("--source-role-arn", required=True, help="ARN of a role the account to back up _from_")
@click.option("--destination-role-arn", required=True, help="ARN of an assumable role in the account to back up _to_")
@click.option("--dry-run", is_flag=True, help="Don't back anything up, just list would be backed up")
@click.pass_context
def backup(ctx, region, source_role_arn, destination_role_arn, dry_run):
    """
    Backup subcommand. Does nothing by itself except pass the global options through to it's
    subcommands via ctx
    """

    ctx.obj = {
        'region': region,
        'source_role_arn': source_role_arn,
        'destination_role_arn': destination_role_arn,
        'dry_run': dry_run,
        'log_level': ctx.obj.get('log_level')
    }

    pass

@backup.command()
@click.pass_context
@click.option("--take-snapshot", is_flag=True, help="TODO: Boolean, default false. Take a live snapshot now, or take the existing latest snapshot")
@click.option("--db-arns", required=False, help="Comma separated list of either DB names or ARNs to transfer")
def rds(ctx, take_snapshot, db_arns):
    """
    Backup all RDS instances found if --db-arns is omitted, else look for the latest
    snapshots for those DB names given and transfer them to the destination account
    """

    region = ctx.obj.get('region')
    source_role_arn = ctx.obj.get('source_role_arn')
    destination_role_arn = ctx.obj.get('destination_role_arn')
    dry_run = ctx.obj.get('dry_run')

    if db_arns:
        db_arns = [db_arns.replace(' ','')]
    else:
        scanner = scan_resources_storage.ScanResources(region, source_role_arn)
        db_arns = db_arns or scanner.scan_rds()['rds_arns']

    logging.info("Will attempt to backup the following RDS instances, unless this is a dry run:")
    logging.info(db_arns)

    if dry_run:
        exit(0)

    from .rds import transfer_snapshot
    rds = transfer_snapshot.TransferSnapshot(
        region=region,
        source_role_arn=source_role_arn,
        destination_role_arn=destination_role_arn
    )

    shared_kms_key = rds.get_shared_kms_key()
    rds.transfer_snapshot(take_snapshot=take_snapshot, db_arns=db_arns, source_kms_key=shared_kms_key)
