import click
from akinaka_libs import helpers
import logging

helpers.set_logger()

@click.group()
@click.option("--region", required=True, help="Region your resources are located in")
@click.option("--role-arns", required=True, help="Role ARNs with assumable permissions, to do the cleanup for")
@click.option("--not-dry-run", is_flag=True, help="Will do nothing unless supplied")
@click.pass_context
def cleanup(ctx, region, role_arns, not_dry_run=False):
    ctx.obj = {'region': region, 'role_arns': role_arns, 'not_dry_run': not_dry_run}
    pass


@cleanup.command()
@click.pass_context
@click.option("--retention", type=int, required=True, help="How long to hold AMIs for")
@click.option("--exceptional-amis", help="List of AMI names to always keep just the latest version of (useful for base images)")
@click.option("--launch-templates", help="List of Launch Templates to check AMI usage against. If AMI appears in latest version, it will be spared")
def ami(ctx, retention, exceptional_amis, launch_templates):
    from .ami import cleanup_amis
    region = ctx.obj.get('region')
    not_dry_run = ctx.obj.get('not_dry_run')
    role_arns = ctx.obj.get('role_arns')
    role_arns = role_arns.split(" ")

    if exceptional_amis:
        exceptional_amis = exceptional_amis.split(" ")
    else:
        exceptional_amis = []

    if launch_templates:
        launch_templates = launch_templates.split(" ")
    else:
        launch_templates = []

    try:
        amis = cleanup_amis.CleanupAMIs(region, role_arns, retention, not_dry_run, exceptional_amis, launch_templates)
        amis.cleanup()
        exit(0)
    except Exception as e:
        logging.error(e)
        exit(1)

@cleanup.command()
@click.pass_context
def ebs(ctx):
    from .ebs import cleanup_volumes
    region = ctx.obj.get('region')
    not_dry_run = ctx.obj.get('not_dry_run')
    role_arns = ctx.obj.get('role_arns')
    role_arns = role_arns.split(" ")

    try:
        volumes = cleanup_volumes.CleanupVolumes(region, role_arns, not_dry_run)
        volumes.cleanup()
        exit(0)
    except Exception as e:
        logging.error(e)
        exit(1)

@cleanup.command()
@click.option("--search-tags", required=True, help="Comma separated list of tags attached to snapshots to be deleted")
@click.pass_context
def rds(ctx, search_tags):
    from .rds import cleanup_snapshots
    region = ctx.obj.get('region')
    not_dry_run = ctx.obj.get('not_dry_run')
    role_arns = ctx.obj.get('role_arns')
    role_arns = role_arns

    try:
        snapshots = cleanup_snapshots.CleanupSnapshots(region, role_arns, search_tags, not_dry_run)
        snapshots.cleanup()
        exit(0)
    except Exception as e:
        logging.error(e)
        exit(1)
