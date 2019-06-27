import click
from akinaka_client.aws_client import AWS_Client
from akinaka_libs import helpers
from time import gmtime, strftime
import logging

helpers.set_logger()

@click.group()
def k8s():
    pass

@k8s.command()
@click.option("--applications", required=True, help="Comma separated list of containers to update")
@click.option("--new-image", help="Full image path, minus the tag")
@click.option("--new-tag", help="Tag to update the container's image to")
@click.option("--file-paths", required=True, help="Comma separated string with paths to deployment specs")
@click.option("--dry-run", is_flag=True, help="If passed, then the new config is written to stdout instead of the originating file")
def update_deployment(applications, new_image, new_tag, file_paths, dry_run):
    from .update_deployment import update_deployment

    k8s_update = update_deployment.UpdateDeployment(applications, new_image, new_tag, file_paths, dry_run)
    k8s_update.write_new_spec()
