import click
from akinaka.client.aws_client import AWS_Client
from akinaka.libs import helpers
from time import gmtime, strftime
import logging

@click.group()
@click.option("--region", required=True, help="Region your resources are located in")
@click.option("--role-arn", required=True, help="Role ARN which contains necessary assume permissions")
@click.pass_context
def update(ctx, region, role_arn):
    """
    Update subcommand. Does nothing by itself except pass the global options through to it's
    subcommands via ctx
    """

    ctx.obj = {'region': region, 'role_arn': role_arn, 'log_level': ctx.obj.get('log_level')}
    pass

def set_deploy_status(verb, region, role_arn, application, reset=None):
    """
    Set the status of this deploy to started by setting a timestamp in the application's
    deploying-status-APPLICATION_NAME SSM parameter
    """

    aws_client = AWS_Client()
    ssm_client = aws_client.create_client('ssm', region, role_arn)
    ssm_parameter_name = "deploying-status-{}".format(application)

    try:
        deploying_state = ssm_client.get_parameter(Name=ssm_parameter_name)['Parameter']['Value']
    except ssm_client.exceptions.ParameterNotFound:
        deploying_state = "false"

    if verb == "start" and deploying_state != "false" and reset != True:
        logging.error("Refusing to deploy, since it looks like we're already deploying at this timestamp: {}".format(deploying_state))
        exit(1)
    elif verb == "stop":
        new_state = "false"
    elif verb == "start":
        new_state = strftime("%Y%m%d%H%M%S", gmtime())

    ssm_client.put_parameter(
        Name=ssm_parameter_name,
        Description="Whether we're deploying right now",
        Value=new_state,
        Type="String",
        Overwrite=True
    )
    logging.info("Deployment status for {} updated".format(application))

@update.command()
@click.pass_context
@click.option("--application-name", required=True, help="The application name (target group) to reset unlock for re-running the 'asg' subcommand on")
def reset(ctx, application_name):
    """ Reset the deploy status of an application. Use with caution """

    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')
    set_deploy_status("stop", region, role_arn, application_name, True)

@update.command()
@click.pass_context
@click.option("--ami", required=True, help="Update ASG to this AMI")
@click.option("--lb", help="Loadbalancer to work out targetgroup from -- mutually exclusive with --asg and --target-group")
@click.option("--target-group", "target_group", help="Target Group to discover the ASG for updating. Mutually exclusive with --asg and --lb")
@click.option("--asg", "asg_name", help="ASG we're updating -- mutually exclusive with --lb and --target-group")
@click.option("--skip-status-check", "skip_status_check", is_flag=True, default=False, help="When passed, skips checking if we're already in the middle of a deploy")
def asg(ctx, ami, lb, asg_name, target_group, skip_status_check):
    """
    Update an ASG by scaling it down and up again with the new launch template configuration. Can be
    used in three different modes, the first two being geared towards blue/green deploys:

    --lb:           launch template will be worked out by querying the load balancer. Only applicable for load
                    balancers with a single ASG
    --target-group: launch template will be worked out by querying the target group (then the load balancer).
                    Used when the load balancer is attached to more than one ASG
    --asg:          For when you already know which ASG you want to update. Used for non-blue/green deploys,
                    such as ASGs for workers
    """

    if [lb, asg_name, target_group].count(None) < 2:
        logging.error("--lb, --asg, and --target-group are mutually exclusive. Please use only one")

    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')

    from .asg import update_asg

    asg = update_asg.ASG(region, role_arn)
    application = asg.get_application_name(asg=asg_name, loadbalancer=lb, target_group=target_group)

    if lb or target_group:
        if not skip_status_check:
            set_deploy_status("start", region, role_arn, application)

    asg.do_update(ami, asg=asg_name, loadbalancer=lb, target_group=target_group)
    exit(0)

@update.command()
@click.pass_context
@click.option("--new", "new_asg_target", help="The ASG we're switching the LB to (attaching this ASG to the LB's targetgroup)")
def targetgroup(ctx, new_asg_target):
    """
    Switch the load balancer to serve from a different ASG by attaching the new one and detaching the
    old one, from the target group
    """

    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')
    log_level = ctx.obj.get('log_level')

    from .targetgroup import update_targetgroup

    try:
        target_groups = update_targetgroup.TargetGroup(region, role_arn, new_asg_target, log_level)
        target_groups.switch_asg()
        # We've successfully deployed, so set the status of deploy to "false"
        set_deploy_status("stop", region, role_arn, target_groups.get_application_name())
        exit(0)
    except Exception as e:
        logging.error("{}".format(e))
        exit(1)

@update.command()
@click.pass_context
@click.option("--active-asg", "active_asg", help="Name of the currently active ASG")
@click.option("--skip-status-check", "skip_status_check", is_flag=True, default=False, help="When passed, skips checking if we're already in the middle of a deploy")
def scale_down_inactive(ctx, active_asg, skip_status_check):
    """
    Given an the name of the _active_ ASG, scale down the inactive one. Only useful for
    blue/green deploys
    """

    region = ctx.obj.get('region')
    role_arn = ctx.obj.get('role_arn')

    from .asg import update_asg

    asg = update_asg.ASG(region=region, role_arn=role_arn)

    asg.scale_down_inactive(active_asg)
    exit(0)
