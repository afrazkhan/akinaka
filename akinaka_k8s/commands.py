import click
from akinaka_client.aws_client import AWS_Client
from akinaka_libs import helpers
from time import gmtime, strftime
import logging

helpers.set_logger()

@click.group()
@click.option("--applications", required=True, help="Comma separated list of containers to update")
@click.option("--server", required=True, help="Kubernetes server address")
@click.option("--token", required=True, help="Authentication token")
@click.option("--ca-file-path", required=True, help="Path to a file with the server's CA")
@click.pass_context
def k8s(ctx, applications, server, token, ca_file_path):
    from kubernetes import client, config

    configuration = client.Configuration()
    configuration.host = "https://{}".format(server)
    configuration.ssl_ca_cert = ca_file_path
    configuration.debug = True
    configuration.api_key={"authorization":"Bearer {}".format(token)}

    ctx.obj = {'configuration': configuration, 'applications': applications}

    pass

@k8s.command()
@click.pass_context
def monitor_deployment(ctx):
    applications = ctx.obj.get('applications')
    configuration = ctx.obj.get('configuration')

    from .monitor_deployment import monitor_deployment
    k8s_monitor = monitor_deployment.MonitorDeployment(configuration, applications)
    k8s_monitor.list_all()


@k8s.command()
@click.option("--new-image", help="Full image path, minus the tag")
@click.option("--new-tag", help="Tag to update the container's image to")
@click.option("--file-paths", required=True, help="Comma separated string with paths to deployment specs")
@click.option("--dry-run", is_flag=True, help="If passed, then the new config is written to stdout instead of the originating file")
@click.pass_context
def update_deployment(ctx, new_image, new_tag, file_paths, dry_run):
    applications = ctx.obj.get('applications')
    configuration = ctx.obj.get('configuration')

    from .update_deployment import update_deployment

    k8s_update = update_deployment.UpdateDeployment(applications, new_image, new_tag, file_paths, dry_run)
    k8s_update.write_new_spec()
