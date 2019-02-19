#!/usr/bin/env python3

import click
from time import gmtime, strftime
from akinaka_update import update
from akinaka_cleanup import cleanup

@click.group()
def cli():
    pass

cli.add_command(update)
cli.add_command(cleanup)

cli()