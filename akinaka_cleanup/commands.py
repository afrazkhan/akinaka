import click

@click.group()
@click.option("--region", required=True, help="Region your resources are located in")
@click.option("--role-arns", required=True, help="Role ARNs with assumable permissions, to do the cleanup for")
@click.pass_context
def cleanup(ctx, region, role_arns):
    ctx.obj = {'region': region, 'role_arns': role_arns}
    pass


@cleanup.command()
@click.pass_context
@click.option("--retention", type=int, required=True, help="How long to hold AMIs for")
@click.option("--not-dry-run", is_flag=True, help="Will do nothing unless supplied")
@click.option("--exceptional-amis", help="List of AMI names to always keep just the latest version of (useful for base images)")
def ami(ctx, retention, not_dry_run, exceptional_amis):
    from .ami import cleanup_amis
    region = ctx.obj.get('region')
    role_arns = ctx.obj.get('role_arns')
    role_arns = role_arns.split(" ")

    if exceptional_amis:
        exceptional_amis = exceptional_amis.split(" ")
    else:
        exceptional_amis = []

    try:
        amis = cleanup_amis.CleanupAMIs(region, role_arns, retention, not_dry_run, exceptional_amis)
        amis.cleanup()
        exit(0)
    except Exception as e:
        print(e)
        exit(1)




