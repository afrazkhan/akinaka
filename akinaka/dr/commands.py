import click
from akinaka.client.aws_client import AWS_Client
from akinaka.libs import helpers, scan_resources_storage
from akinaka.libs import helpers, kms_share
from time import gmtime, strftime
import logging

aws_client = AWS_Client()
helpers.set_logger()

@click.group()
@click.option("--region", required=True, help="Region your resources are located in")
@click.option("--source-role-arn", required=True, help="ARN of a role the account to back up _from_")
@click.option("--destination-role-arn", required=True, help="ARN of an assumable role in the account to back up _to_")
@click.option("--dry-run", is_flag=True, help="Don't back anything up, just list would be backed up")
@click.pass_context
def dr(ctx, region, source_role_arn, destination_role_arn, dry_run):
    """
    Disaster recovery subcommand. Does nothing by itself except pass the global options through to it's
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

def get_shared_kms_key(region, source_role_arn, source_account, destination_account):
    """
    Create and return shared KMS account between [source_account] and [destination_account]
    """

    kms_sharer = kms_share.KMSShare(
        region = region,
        assumable_role_arn = source_role_arn,
        share_from_account = source_account,
        share_to_account = destination_account
    )

    return kms_sharer.get_kms_key(source_account)

def create_kms_key(region, assumable_role_arn):
    """
    Search for a key name that should exists if this has been run before. If not found,
    create it. In both cases, return the key.
    """

    kms_client = aws_client.create_client('kms', region, assumable_role_arn)
    key_alias = "alias/Akinaka"

    try:
        kms_key = kms_client.describe_key(KeyId=key_alias)
        logging.info("Found key: {}".format(kms_key['KeyMetadata']['Arn']))
    except kms_client.exceptions.NotFoundException:
        kms_key = kms_client.create_key()
        logging.info("No existing key found, so we created one: {}".format(kms_key['KeyMetadata']['Arn']))

        kms_client.create_alias(
            AliasName=key_alias,
            TargetKeyId=kms_key['KeyMetadata']['Arn']
        )

    return kms_key


@dr.command()
@click.pass_context
@click.option("--take-snapshot", is_flag=True, help="Boolean, default false. Take a live snapshot now, or take the existing latest snapshot. Relevant only for RDS")
@click.option("--names", required=False, help="Comma separated list in quotes of DB/S3 names to transfer")
@click.option("--service", type=click.Choice(['rds', 'aurora', 's3']), required=False, help="The service to transfer backups for. Defaults to all (RDS, S3)")
@click.option("--retention", required=False, help="Number of days of backups to keep")
@click.option("--rotate", is_flag=True, required=False, help="Only rotate backups so [retention] number of days is kept, don't do any actual backups. Relevant for RDS only")
@click.option("--keep", required=False, help="Comma separated list in quotes. Do not delete these snapshot IDs as part of the rotation policy.")
def transfer(ctx, take_snapshot, names, service, retention, keep, rotate):
    """
    Creates and passes shared KMS keys to the subcommands which wish to tranfer data between eachother.

    Backup [service] from owning account of [ctx.source_role_arn] to owning account
    of [ctx.destination_role_arn].
    """

    region = ctx.obj.get('region')
    source_role_arn = ctx.obj.get('source_role_arn')
    destination_role_arn = ctx.obj.get('destination_role_arn')
    dry_run = ctx.obj.get('dry_run')

    source_sts_client = aws_client.create_client('sts', region, source_role_arn)
    source_account = source_sts_client.get_caller_identity()['Account']
    destination_sts_client = aws_client.create_client('sts', region, destination_role_arn)
    destination_account = destination_sts_client.get_caller_identity()['Account']

    source_kms_key = get_shared_kms_key(region, source_role_arn, source_account, destination_account)
    destination_kms_key = create_kms_key(region, destination_role_arn)

    if service == 'rds':
        if names:
            db_names = [names.replace(' ','')]
        else:
            scanner = scan_resources_storage.ScanResources(region, source_role_arn)
            db_names = scanner.scan_rds_instances()['db_names']

        if keep:
            keep = [keep.replace(' ','')]

        rds(
            dry_run,
            region,
            source_role_arn,
            destination_role_arn,
            take_snapshot,
            db_names,
            source_kms_key,
            destination_kms_key,
            source_account,
            destination_account,
            retention,
            keep,
            rotate)

    if service == 'aurora':
        if names:
            db_names = [names.replace(' ','')]
        else:
            scanner = scan_resources_storage.ScanResources(region, source_role_arn)
            db_names = scanner.scan_rds_aurora()['aurora_names']

        rds(
            dry_run,
            region,
            source_role_arn,
            destination_role_arn,
            take_snapshot,
            db_names,
            source_kms_key,
            destination_kms_key,
            source_account,
            destination_account,
            retention,
            keep,
            rotate)

    if service == 's3':
        if names:
            names = [names.replace(' ','')]
        else:
            scanner = scan_resources_storage.ScanResources(region, source_role_arn)
            names = scanner.scan_s3()['s3_names']

        s3(
            dry_run,
            region,
            source_role_arn,
            destination_role_arn,
            names,
            source_kms_key,
            destination_kms_key,
            retention
        )

def s3(
        dry_run,
        region,
        source_role_arn,
        destination_role_arn,
        names,
        source_kms_key,
        destination_kms_key,
        retention):
    """ Call the S3 class to make backups of S3 buckets """

    logging.info("Will attempt to backup the following S3 buckets, unless this is a dry run:")
    logging.info(names)

    if dry_run:
        exit(0)

    retention = retention or 7

    from .s3 import transfer_s3
    s3 = transfer_s3.TransferS3(
        region=region,
        source_role_arn=source_role_arn,
        destination_role_arn=destination_role_arn,
        source_kms_key=source_kms_key,
        destination_kms_key=destination_kms_key,
        retention=retention
    )

    s3.main(names)

def rds(
    dry_run,
    region,
    source_role_arn,
    destination_role_arn,
    take_snapshot,
    db_names,
    source_kms_key,
    destination_kms_key,
    source_account,
    destination_account,
    retention,
    keep,
    rotate):
    """
    Call the RDS class to transfer snapshots
    """

    logging.info("Will attempt to backup the data for following RDS instances, unless this is a dry run:")
    logging.info(db_names)

    if dry_run:
        exit(0)

    from .rds import transfer_snapshot
    rds = transfer_snapshot.TransferSnapshot(
        region=region,
        source_role_arn=source_role_arn,
        destination_role_arn=destination_role_arn,
        source_kms_key=source_kms_key,
        destination_kms_key=destination_kms_key
    )

    retention = retention or 7

    if rotate:
        for db_name in db_names:
            rds.rotate_snapshots(retention, db_name, keep)
        exit()

    rds.transfer_snapshot(
        take_snapshot=take_snapshot,
        db_names=db_names,
        source_account=source_account,
        destination_account=destination_account,
        keep=keep,
        retention=retention
    )
