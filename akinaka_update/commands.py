import click
from akinaka_client.aws_client import AWS_Client
from time import gmtime, strftime

@click.group()
@click.option("--region", required=True, help="Region your resources are located in")
@click.option("--role-arn", required=True, help="Role ARN which contains necessary assume permissions")
@click.pass_context
def update(ctx, region, role_arn):
    ctx.obj = {'region': region, 'role_arn': role_arn}
    pass



def set_deploy_status(verb, region, role_arn, reset=None):
    aws_client = AWS_Client()
    ssm_client = aws_client.create_client('ssm', region, role_arn)

    deploying_state = ssm_client.get_parameter(Name="deploying-status")['Parameter']['Value']

    if verb == "start" and deploying_state != "false" and reset != True:
        print("Refusing to deploy, since it looks like we're already deploying at this timestamp: {}".format(deploying_state))
        exit(1)
    elif verb == "stop":
        new_state = "false"
    elif verb == "start":
        new_state = strftime("%Y%m%d%H%M%S", gmtime())

    ssm_client.put_parameter(
        Name="deploying-status",
        Description="Whether we're deploying right now",
        Value=new_state,
        Type="String",
        Overwrite=True
    )


@update.command()
@click.pass_context
def reset(ctx):
    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')
    set_deploy_status("stop", region, role_arn, True)


@update.command()
@click.pass_context
@click.option("--ami", required=True, help="Update ASG to this AMI")
@click.option("--lb", help="Loadbalancer to work out targetgroup from -- mutually exclusive with --asg and --target-group")
@click.option("--target-group", "target_group", help="Target Group to discover the ASG for updating. Mutually exclusive with --asg and --lb")
@click.option("--asg", "asg_name", help="ASG we're updating -- mutually exclusive with --lb and --target-group")
def asg(ctx, ami, lb, asg_name, target_group):
    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')

    from .asg import update_asg

    # We set the deploy status to a timestamp (meaning in progress) if this is an update based on
    # working out the ASG to update from the load balancer, so as not to allow interruption to the
    # processs until we've also updated the targetgroup
    if lb:
        set_deploy_status("start", region, role_arn)

    asg = update_asg.ASG(ami, region, role_arn, lb, asg_name, target_group)
    asg.do_update()
    exit(0)


@update.command()
@click.pass_context
@click.option("--new", "new_asg_target", help="The ASG we're switching the LB to (attaching this ASG to the LB's targetgroup)")
def targetgroup(ctx, new_asg_target):
    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')

    from .targetgroup import update_targetgroup

    try:
        target_groups = update_targetgroup.TargetGroup(region, role_arn, new_asg_target)
        target_groups.switch_asg()
        # We've successfully deployed, so set the status of deploy to "false"
        set_deploy_status("stop", region, role_arn)
        exit(0)
    except Exception as e:
        print(e)
        exit(1)

