#!/usr/bin/env python3

import sys
from time import sleep
from akinaka.libs import helpers
from akinaka.libs import exceptions
from botocore.exceptions import ParamValidationError
from botocore.exceptions import ClientError
from akinaka.client.aws_client import AWS_Client
import logging

aws_client = AWS_Client()

class ASG():
    """All the methods needed to perform a blue/green deploy"""

    def __init__(self, region, role_arn, log_level):
        self.region = region
        self.role_arn = role_arn
        logging.getLogger().setLevel(log_level)

    def get_application_name(self, asg, loadbalancer=None, target_group=None):
        """
        Returns the application name that we're deploying, worked out from the target group
        (via the load balancer if applicable)
        """

        if asg:
            return asg

        target_group_arn = self.get_target_group_arn(loadbalancer, target_group)
        active_asg = self.get_active_asg(target_group_arn)
        asg_split = active_asg.split('-')[0:-1]

        return '-'.join(asg_split)

    def asgs_by_liveness(self, asg=None, loadbalancer=None, target_group=None):
        """Return dict of '{inactive: ASG, active: ASG}'"""

        if asg is not None:
            logging.info("We've been given the ASG name as an argument")
            # NOTE: "inactive_asg" is a misnomer at this point, since when we already have the ASG
            #       name, it is also the active ASG, because this case is used for non-blue/green ASGs
            return {"inactive_asg": asg, "active_asg": asg}

        target_group_arn = self.get_target_group_arn(loadbalancer=loadbalancer, target_group=target_group)
        active_asg = self.get_active_asg(target_group_arn)
        inactive_asg = self.get_inactive_asg(active_asg)

        return {"inactive_asg": inactive_asg, "active_asg": active_asg}

    def scale_down_inactive(self, target_group):
        """
        Given [target_group], work out which ASG is the inactive one, and scale it down to 0.

        Returns True on success, or calls sys.exit(1) on failure (via self.scale())
        """
        target_group_arn = self.get_target_group_arn(target_group=target_group)
        active_asg = self.get_active_asg(target_group_arn)
        inactive_asg = self.get_inactive_asg(active_asg)
        self.scale(inactive_asg, 0, 0, 0)

        return True

    def set_asg_launch_template_version(self, asg, lt_id, lt_version):
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)

        asg_client.update_auto_scaling_group(
            AutoScalingGroupName = asg,
            LaunchTemplate = {
                "LaunchTemplateId": lt_id,
                "Version": lt_version
            }
        )

    def rescale(self, active_asg, inactive_asg):
        """
        Scales [inactive_asg] to the same values as those found in [active_asg]

        Returns True on success and exits with a code of 1 if scaling failed
        """

        active_asg_size = self.get_current_scale(active_asg)

        logging.info('Scaling to 0 first to start with a clean slate')
        self.scale(inactive_asg, 0, 0, 0)
        logging.info(f"Scaling ASG {inactive_asg} to {active_asg_size['min']}, {active_asg_size['max']}, {active_asg_size['desired']}")
        logging.info('Scaling to match the numbers from the active ASG')
        self.scale(
            asg = inactive_asg,
            min_size = active_asg_size['min'],
            max_size = active_asg_size['max'],
            desired =  active_asg_size['desired']
        )

        return True

    def asg_instance_list(self, asg):
        """
        TODO: Can this replace get_auto_scaling_group_instances()?

        Return a list of instances from [asg]
        """

        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        asg_info = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg])
        return asg_info['AutoScalingGroups'][0]['Instances']

    def scale_waiter(self, asg, desired_scale, timeout=600):
        """
        Scales [asg] to [desired_scale] and waits [timeout] seconds for all instances
        to become healthy. [timeout] defaults to 600

        Returns True on success, or False on failure
        """

        max_attempts = timeout/20
        attempts = 0

        while len(self.asg_instance_list(asg)) != desired_scale or (len(self.asgs_healthy_instances(asg)) < desired_scale and attempts != max_attempts):
            logging.info("Waiting for scaling event to finish successfully. Next poll in 20 seconds")

            sleep(20)
            attempts += 1
            if attempts == max_attempts:
                logging.info("Timeout reached without success whilst waiting for all instances to become healthy")
                return False

        return True

    def refresh_asg(self, asg):
        """
        UNUSED CODE

        Triggers and monitors an ASG refresh call of [asg]. This function is no longer used,
        but kept since could be useful in some circumstances

        Returns True on success and False on failure
        """

        logging.info(f"Starting instance refresh for ASG {asg}")
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        asg_client.start_instance_refresh(
            AutoScalingGroupName=asg,
            Preferences={
                'MinHealthyPercentage': 0,
                'InstanceWarmup': 0
            }
        )

        refresh_status = asg_client.describe_instance_refreshes(AutoScalingGroupName=asg)['InstanceRefreshes'][0]
        while refresh_status['Status'] != 'Successful':
            logging.info(f"ASG refresh result:\n{refresh_status}\nNext poll in 20 seconds.")
            refresh_status = asg_client.describe_instance_refreshes(AutoScalingGroupName=asg)['InstanceRefreshes'][0]
            if refresh_status['Status'] == 'Failed' or refresh_status['Status'] == 'Cancelling':
                logging.error('The rollout failed, exiting. You must clean up the failed deploy manually')
                return False
            sleep(20)

        return True

    def log_new_asg_name(self, new_asg_name):
        """ Write [new_asg_name] to 'inactive_asg.txt' """

        logging.info("ASG fully healthy. Logging new ASG name to \"inactive_asg.txt\"")
        open("inactive_asg.txt", "w").write(new_asg_name)

    def get_first_new_instance(self, new_asg):
        asg_instances = self.get_auto_scaling_group_instances(new_asg)
        if len(asg_instances) < 1: raise exceptions.AkinakaLoggingError

        return asg_instances[0]['InstanceId']

    def get_instance_console_output(self, instance):
        ec2_client = aws_client.create_client('ec2', self.region, self.role_arn)
        return ec2_client.get_console_output(InstanceId=instance)

    def instance_state(self, instance):
        ec2_client = aws_client.create_client('ec2', self.region, self.role_arn)
        instance_states = ec2_client.describe_instance_status(IncludeAllInstances=True, InstanceIds=[instance])

        while 'InstanceStatuses' not in instance_states:
            instance_states = ec2_client.describe_instance_status(InstanceIds=[instance])

        return instance_states['InstanceStatuses'][0]['InstanceState']['Name']

    def get_lt_name(self, asg):
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        lt_info = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg])

        try:
            return lt_info['AutoScalingGroups'][0]['LaunchTemplate']['LaunchTemplateName']
        except Exception as e:
            raise exceptions.AkinakaCriticalException("{}: Likely couldn't find the ASG you're trying to update".format(e))

    def get_target_group_arn(self, loadbalancer=None, target_group=None):
        """
        Returns a string containing the ARN of the target group, either by using:

        * targetgroup from --targetgroup
        * loadbalancer from --lb

        Both are mutually exclusive, and at least one must be supplied
        """
        alb_client = aws_client.create_client('elbv2', self.region, self.role_arn)
        if target_group is not None:
            try:
                return alb_client.describe_target_groups(Names=[target_group])['TargetGroups'][0]['TargetGroupArn']
            except alb_client.exceptions.TargetGroupNotFoundException as e:
                logging.error(f"Couldn't describe the target group {target_group}. Does it exist?\n{e}")
                all_target_groups_info = alb_client.describe_target_groups()['TargetGroups']
                all_target_groups = [ tg['TargetGroupName'] for tg in all_target_groups_info ]
                logging.error(f"Here's a list of all target groups I could find. Some may belong to different deployments: {all_target_groups}")
                sys.exit(1)

        loadbalancer_raw_info = alb_client.describe_load_balancers(Names=[loadbalancer])
        loadbalancer_arn = loadbalancer_raw_info['LoadBalancers'][0]['LoadBalancerArn']

        target_groups_raw_info = alb_client.describe_target_groups(LoadBalancerArn=loadbalancer_arn)['TargetGroups']
        target_group_arns = [targetgroup['TargetGroupArn'] for targetgroup in target_groups_raw_info]

        # If we get this far, then the LB has more than a single target group, and we can't work
        # out which one the caller wants
        if len(target_group_arns) == 1:
            return target_group_arns[0]
        elif len(target_group_arns) > 1:
            error_message = "Load balancer has {} target groups".format(len(target_group_arns))

            for target_group in target_group_arns:
                error_message += "> " + target_group
        else:
            error_message = "Load balancer has no target groups"

        raise exceptions.AkinakaCriticalException(error_message)

    def get_target_groups_instances(self, target_group_arn):
        """Returns an array of instance IDs belonging to the target group specified"""
        alb_client = aws_client.create_client('elbv2', self.region, self.role_arn)

        target_groups_instances = []

        these_target_group_instances = alb_client.describe_target_health(TargetGroupArn=target_group_arn)['TargetHealthDescriptions']
        these_target_group_instances = [
            instance for instance in these_target_group_instances if not instance['TargetHealth']['State'] == "unused"
        ]

        # NOTE: This presumes some robustness from your target groups. If they contain instances
        #       from stale ASGs, or anything else is off in them, you will get unexpected results
        for instance in these_target_group_instances:
            target_groups_instances.append(instance['Target']['Id'])

        return target_groups_instances

    def get_active_asg(self, target_groups):
        ec2_client = aws_client.create_client('ec2', self.region, self.role_arn)

        target_groups_instances = self.get_target_groups_instances(target_groups)

        instances_with_tags = {}

        raw_instances_reservations = ec2_client.describe_instances(InstanceIds=target_groups_instances)['Reservations']

        for reservation in raw_instances_reservations:
            for instance in reservation['Instances']:
                instances_with_tags[instance['InstanceId']] = instance['Tags']

        instances_with_asg = {}

        # Create dictionary with Instance -> AG
        for (key,value) in instances_with_tags.items():
            for tag in value:

                if tag['Key'] == 'aws:autoscaling:groupName':
                    instances_with_asg[key] = tag['Value']

        return next(iter(instances_with_asg.values()))

    def get_inactive_asg(self, active_asg):
        asg_parts = active_asg.split('-')
        active_colour = asg_parts[-1]

        if active_colour == "blue":
            inactive_colour = "green"
        else:
            inactive_colour = "blue"

        asg_parts[-1] = inactive_colour

        return "-".join(asg_parts)

    def get_launch_template_info(self, lt_name):
        """Returns the [id] and (latest) [version] number for lt_name"""

        ec2_client = aws_client.create_client('ec2', self.region, self.role_arn)

        response = ec2_client.describe_launch_templates(
            DryRun=False,
            Filters=[
                {
                    'Name': 'launch-template-name',
                    'Values': [ lt_name ]
                }
            ]
        )

        # FIXME: This is hackish because we are assuming that there is going to be only 1 (one) launch template
        return {
            "id": response['LaunchTemplates'][0]['LaunchTemplateId'],
            "version": str(response['LaunchTemplates'][0]['LatestVersionNumber'])
        }

    def update_launch_template(self, ami, lt_name):
        """
        Creates a new template version for [lt_name] which uses [ami], and sets the default
        default template version to be that version.

        Returns [id] and (new) [version] number
        """

        lt = self.get_launch_template_info(lt_name)
        lt_client  = aws_client.create_client('ec2', self.region, self.role_arn)

        response = lt_client.create_launch_template_version(
            DryRun = False,
            LaunchTemplateId = lt['id'],
            SourceVersion = str(lt['version']),
            LaunchTemplateData = {
                "ImageId": ami
            }
        )

        launch_template_new_version = str(response['LaunchTemplateVersion']['VersionNumber'])

        lt_client.modify_launch_template(
            LaunchTemplateId=lt['id'],
            DefaultVersion=launch_template_new_version
        )

        return {
            "id": lt['id'],
            "version": launch_template_new_version
        }

    def scale(self, asg, min_size, max_size, desired):
        """
        Scale [asg] to {'min_size', 'max_size', 'desired'}, using scale_waiter()
        to wait for the ASG to be healthy again

        Returns the response from the call on success, or calls sys.exit(1) on failure
        """

        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        response = asg_client.update_auto_scaling_group(
            AutoScalingGroupName=asg,
            MinSize=min_size,
            MaxSize=max_size,
            DesiredCapacity=desired
        )

        if self.scale_waiter(asg, desired) == False:
            sys.exit(1)

        return response

    def get_current_scale(self, asg):
        """
        Returns the current scales of [asg] as dict {'desired', 'min', 'max'}
        """

        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        asg = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg])['AutoScalingGroups'][0]

        return {
            "desired": asg['DesiredCapacity'],
            "min": asg['MinSize'],
            "max": asg['MaxSize']
        }

    def get_auto_scaling_group_instances(self, auto_scaling_group_id, instance_ids=None):
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        instance_ids = instance_ids if instance_ids else []
        asg_instances = asg_client.describe_auto_scaling_instances(InstanceIds=instance_ids)
        target_instances = []

        for i in asg_instances['AutoScalingInstances']:
            if i['AutoScalingGroupName'] == auto_scaling_group_id:
                target_instances.append(i)

                logging.info("Instance {instance_id} has state = {instance_state}, "
                    "Lifecycle is at {instance_lifecycle_state}".format(
                        instance_id = i['InstanceId'],
                        instance_state = i['HealthStatus'],
                        instance_lifecycle_state = i['LifecycleState']
                    )
                )

                logging.info("Instance {instance_id} is {instance_lifecycle_state}".format(
                        instance_id = i['InstanceId'],
                        instance_lifecycle_state = i['LifecycleState']
                    )
                )


        return target_instances

    def asg_is_empty(self, auto_scaling_group_id):
        asg_instances = self.get_auto_scaling_group_instances(auto_scaling_group_id)

        return all(instance.get('LifecycleState') == 'Terminated' for instance in asg_instances)

    def asgs_healthy_instances(self, auto_scaling_group_id):
        asg_instances = self.get_auto_scaling_group_instances(auto_scaling_group_id)
        healthy_instances = []

        for i in asg_instances:
            if i['LifecycleState'] == "InService":
                healthy_instances.append(i)

        return healthy_instances

    def main(self, ami, asg=None, loadbalancer=None, target_group=None):
        """
        Calls necessary methods to perform an update:

        1. Figures out which ASGs are active and inactive
        2. Creates new launch template version with AMI set to [ami]
        3. Scales inactive ASG down, then back up using the new launch template version
        """

        asg_liveness_info = self.asgs_by_liveness(asg=asg, loadbalancer=loadbalancer, target_group=target_group)

        inactive_asg = asg_liveness_info['inactive_asg']
        active_asg = asg_liveness_info['active_asg']
        new_ami = ami

        logging.info("New ASG was worked out as {}. Now updating it's Launch Template".format(inactive_asg))

        updated_lt = self.update_launch_template(new_ami, self.get_lt_name(inactive_asg))
        self.set_asg_launch_template_version(
            asg=inactive_asg,
            lt_id=updated_lt["id"],
            lt_version=updated_lt["version"]
        )

        self.rescale(active_asg, inactive_asg)

        self.log_new_asg_name(inactive_asg)
