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
@click.option("--application", required=True, help="The container to update")
@click.option("--new-image", help="Full image path, minus the tag")
@click.option("--new-tag", help="Tag to update the container's image to")
@click.option("--file-path", default="kubernetes/deployment.yml", help="Alternative path to deployment spec. Defaults to 'kubernetes/deployment.yml'")
@click.option("--dry-run", is_flag=True, help="If passed, then the new config is written to stdout instead of the originating file")
def update_deployment(application, new_image, new_tag, file_path, dry_run):
    from .update_deployment import update_deployment

    k8s_update = update_deployment.UpdateDeployment(application, new_image, new_tag, file_path, dry_run)
    k8s_update.write_new_spec()
