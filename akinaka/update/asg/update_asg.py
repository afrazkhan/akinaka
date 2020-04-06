#!/usr/bin/env python3

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

    def __init__(self, region, role_arn):
        self.region = region
        self.role_arn = role_arn

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

    def scale_down_inactive(self, asg):
        # NOTE: We're making the heavy presumption here that the _active_ ASG is the one we've been
        #       given from the command line
        inactive_asg = self.get_inactive_asg(asg)
        self.scale(inactive_asg, 0, 0, 0)

    def set_asg_launch_template_version(self, asg, lt_id, lt_version):
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)

        asg_client.update_auto_scaling_group(
            AutoScalingGroupName = asg,
            LaunchTemplate = {
                "LaunchTemplateId": lt_id,
                "Version": lt_version
            }
        )

    def do_update(self, ami, asg=None, loadbalancer=None, target_group=None):
        asg_liveness_info = self.asgs_by_liveness(asg=asg, loadbalancer=loadbalancer, target_group=target_group)

        inactive_asg = asg_liveness_info['inactive_asg']
        active_asg = asg_liveness_info['active_asg']
        new_ami = ami

        logging.info("New ASG was worked out as {}. Now updating it's Launch Template".format(inactive_asg))

        # Update the lt and set the soon to be new ASG to the new launch template version
        updated_lt = self.update_launch_template(new_ami, self.get_lt_name(inactive_asg))
        self.set_asg_launch_template_version(
            asg=inactive_asg,
            lt_id=updated_lt["id"],
            lt_version=updated_lt["version"]
        )

        scale_to = self.get_current_scale(active_asg)

        logging.info("Scaling ASG '{}' down to ({}, {}, {})".format(inactive_asg, 0, 0, 0))
        self.scale(inactive_asg, 0, 0, 0)
        while not self.asg_is_empty(inactive_asg):
            logging.info("Waiting for instances in ASG '{}' to terminate".format(inactive_asg))
            sleep(10)

        logging.info("Scaling ASG '{}' back up to ({}, {}, {})".format(inactive_asg, scale_to['min'], scale_to['max'], scale_to['desired']))
        self.scale(
            auto_scaling_group_id = inactive_asg,
            min_size = scale_to['min'],
            max_size = scale_to['max'],
            desired =  scale_to['desired']
        )

        while len(self.get_auto_scaling_group_instances(inactive_asg)) < 1:
            logging.info("Waiting for instances in ASG to start ...")
            sleep(10)

        logging.info("First instance has started")

        # Try to get information for an instance in the new ASG 20 times
        for i in range(20):
            try:
                first_new_instance = self.get_first_new_instance(inactive_asg)
                if i == 20:
                    raise exceptions.AkinakaCriticalException
                break
            except exceptions.AkinakaLoggingError as error:
                logging.info("Retry {}".format(i))
                logging.info("Problem in getting data for first new ASG instance")
                logging.info("get_auto_scaling_group_instances() returned: {}".format(self.get_auto_scaling_group_instances(inactive_asg)))
                logging.info("Error was: {}".format(error))

        # Show console output for first instance up until it's Lifecycle Hook has passed
        while self.get_auto_scaling_group_instances(auto_scaling_group_id=inactive_asg, instance_ids=[first_new_instance])[0]['LifecycleState'] != "InService":
            try:
                logging.info("Attempting to retrieve console output from first instance up -- this will not work for non-nitro hypervisor VMs")
                logging.info(self.get_instance_console_output(first_new_instance)['Output'])
            except KeyError:
                logging.info("No output from instance yet. Trying again in 10 seconds.")
            sleep(10)

        # Wait for remaining instances (if any) to come up too (up to 5 minutes = 300 attempts)
        attempts = 0
        max_attempts = 300
        while len(self.asgs_healthy_instances(inactive_asg)) < scale_to['desired'] and attempts != max_attempts:
            logging.info("Waiting for all instances to be healthy ...")
            sleep(1)
            attempts += 1
            if attempts == max_attempts:
                logging.info("Max timeout reached without success... Exiting!")
                raise exceptions.AkinakaLoggingError

        logging.info("ASG fully healthy. Logging new ASG name to \"inactive_asg.txt\"")
        open("inactive_asg.txt", "w").write(inactive_asg)

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
            return alb_client.describe_target_groups(Names=[target_group])['TargetGroups'][0]['TargetGroupArn']

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

    def scale(self, auto_scaling_group_id, min_size, max_size, desired):
        """Scale an ASG to {'min_size', 'max_size', 'desired'}"""

        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)

        response = asg_client.update_auto_scaling_group(
            AutoScalingGroupName=auto_scaling_group_id,
            MinSize=min_size,
            MaxSize=max_size,
            DesiredCapacity=desired
        )

        return response

    def get_current_scale(self, asg):
        """
        Returns the current scales of the given ASG as dict {'desired', 'min', 'max'},
        expects ASG ID as argument
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

                logging.debug("Instance {instance_id} has state = {instance_state},"
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
