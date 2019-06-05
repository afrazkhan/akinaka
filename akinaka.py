#!/usr/bin/env python3

import click
from time import gmtime, strftime
from akinaka_update.commands import update as update_commands
from akinaka_cleanup.commands import cleanup as cleanup_commands
from akinaka_rds.commands import copy as copy_commands
from akinaka_reporting.commands import reporting as reporting_commands
from akinaka_container.commands import container as container_commands
from akinaka_k8s.commands import k8s as k8s_commands

@click.group()
def cli():
    pass

cli.add_command(update_commands)
cli.add_command(cleanup_commands)
cli.add_command(copy_commands)
cli.add_command(reporting_commands)
cli.add_command(container_commands)
cli.add_command(k8s_commands)

cli()
