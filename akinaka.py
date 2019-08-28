#!/usr/bin/env python3

import click
from akinaka_libs import helpers
from time import gmtime, strftime
from akinaka_update.commands import update as update_commands
from akinaka_cleanup.commands import cleanup as cleanup_commands
from akinaka_rds.commands import copy as copy_commands
from akinaka_reporting.commands import reporting as reporting_commands
from akinaka_container.commands import container as container_commands
from akinaka_k8s.commands import k8s as k8s_commands

@click.group()
@click.option("--log-level", '-l', default="INFO", type=click.Choice(["INFO", "ERROR", "DEBUG"]), help="How much information to show in logging. Default is INFO")
@click.pass_context
def cli(ctx=None, log_level=None):
    ctx.obj = {'log_level': log_level}

cli.add_command(update_commands)
cli.add_command(cleanup_commands)
cli.add_command(copy_commands)
cli.add_command(reporting_commands)
cli.add_command(container_commands)
cli.add_command(k8s_commands)

cli()
