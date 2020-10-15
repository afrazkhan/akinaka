""" TODO """

import click
from akinaka.client.aws_client import AWS_Client
from akinaka.libs import helpers
import logging
import sys

helpers.set_logger()
aws_client = AWS_Client()

@click.group()
@click.option("--applications", help="Comma separated list of containers to update")
@click.option("--server", help="URL that Kubernetes control plane can be reached (with protocol)")
@click.option("--token", help="Authentication token")
@click.option("--ca-file-path", help="Path to a file with the server's CA")
@click.option("--skip-auth", is_flag=True, help="Temporary flag for skipping auth while we don't need it for other commands")
@click.pass_context
def k8s(ctx, applications, server, token, ca_file_path, skip_auth):
    """ TODO """

    if skip_auth:
        ctx.obj = {'applications': applications, 'log_level': ctx.obj.get('log_level')}
    else:
        from kubernetes import client

        configuration = client.Configuration()
        configuration.host = server
        configuration.ssl_ca_cert = ca_file_path
        configuration.debug = True
        configuration.api_key={"authorization":"Bearer {}".format(token)}

        ctx.obj = {'configuration': configuration, 'applications': applications, 'log_level': ctx.obj.get('log_level')}


@k8s.command()
@click.pass_context
@click.option("--namespace", help="Kubernetes namespace")
@click.option("--deployment", help="Deployment name")
def monitor_deployment(ctx, namespace, deployment):
    """ TODO """

    # applications = ctx.obj.get('applications')
    configuration = ctx.obj.get('configuration')

    from .deployment import deployment as k8s_deployment # pylint: disable=import-outside-toplevel
    k8s_monitor = k8s_deployment.Deployment(configuration)
    k8s_monitor.monitor_update(namespace, deployment)


@k8s.command()
@click.option("--new-image", "-i", help="Full image path, minus the tag")
@click.option("--new-tag", "-t", help="Tag to update the container's image to")
@click.option("--directories", "-d", default=".", help="Comma separated list of directories in which manifests are to be found. Defaults to current")
@click.option("--containers", "-c", required=True, help="Comma separated list of containers in the manifests to update images for")
@click.option("--dry-run", is_flag=True, help="Flag: Write config to stdout instead of the originating file")
@click.pass_context
def edit_manifests(ctx, new_image, new_tag, directories, containers, dry_run):
    """ TODO """

    log_level = ctx.obj.get('log_level')

    if not new_image and not new_tag:
        logging.error("At least --new-image or --new-tag need to be given")
        sys.exit(1)

    from .manifest import manifest # pylint: disable=import-outside-toplevel

    k8s_manifest = manifest.Manifest(dry_run=dry_run, log_level=log_level)
    k8s_manifest.update_image(containers=containers, new_image=new_image, new_tag=new_tag, directories=directories)
