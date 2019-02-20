#!/usr/bin/env python3

import click
from time import gmtime, strftime
from akinaka_update.commands import update as update_commands
from akinaka_cleanup.commands import cleanup as cleanup_commands

@click.group()
def cli():
    pass

cli.add_command(update_commands)
cli.add_command(cleanup_commands)

cli()