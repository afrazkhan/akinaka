#!/usr/bin/env python3

from time import sleep
from akinaka_libs import helpers
from akinaka_libs import exceptions
from akinaka_client.aws_client import AWS_Client
import logging

aws_client = AWS_Client()

class ASG():
    """All the methods needed to perform a blue/green deploy"""

    def __init__(self, ami, region, role_arn, loadbalancer=None, asg=None, target_group=None, scale_to=None):
        self.loadbalancer = loadbalancer
        self.ami = ami
        self.region = region
        self.role_arn = role_arn
        self.asg = asg
        self.target_group = target_group
        self.scale_to = scale_to if scale_to else 1

    def get_application_name(self):
        """
        Returns the application name that we're deploying, worked out from the target group
        (via the load balancer if applicable)
        """
        
        target_group_arn = self.get_target_group_arn()
        active_asg = self.get_active_asg(target_group_arn)
        asg_split = active_asg.split('-')[0:-1]
        
        return '-'.join(asg_split)

    def work_out_new_asg(self):
        if self.asg is not None:
            logging.info("We've been given the ASG name as an argument")
            return self.asg
        
        target_group_arn = self.get_target_group_arn()        
        active_asg = self.get_active_asg(target_group_arn)
        new_asg = self.get_inactive_asg(active_asg)        

        return new_asg

    def do_update(self):
        new_asg = self.work_out_new_asg()
        new_ami = self.ami

        logging.info("New ASG was worked out as {}. Now updating it's Launch Template".format(new_asg))
        self.update_launch_template(new_asg, new_ami, self.get_lt_name(new_asg))
        
        logging.info("Scaling ASG down")
        self.scale(new_asg, 0, 0, 0)
        while not self.asg_is_empty(new_asg):
            logging.info("Waiting for instances in ASG to terminate")
            sleep(10)

        logging.info("Scaling ASG back up")
        self.scale(new_asg, self.scale_to, self.scale_to, self.scale_to)
        
        while len(self.get_auto_scaling_group_instances(new_asg)) < 1:
            logging.info("Waiting for instances in ASG to start ...")
            sleep(10)
            
        logging.info("First instance has started")

        # Try to get information for an instance in the new ASG 20 times
        for i in range(20):
            try:
                first_new_instance = self.get_first_new_instance(new_asg)
                if i == 20:
                    raise exceptions.AkinakaCriticalException
                break
            except exceptions.AkinakaLoggingError as error:
                logging.info("Retry {}".format(i))
                logging.info("Problem in getting data for first new ASG instance")
                logging.info("get_auto_scaling_group_instances() returned: {}".format(self.get_auto_scaling_group_instances(new_asg)))
                logging.info("Error was: {}".format(error))

        # Show console output for first instance up until it's Lifecycle Hook has passed
        while self.get_auto_scaling_group_instances(auto_scaling_group_id=new_asg, instance_ids=[first_new_instance])[0]['LifecycleState'] != "InService":        
            try:
                logging.info("Attempting to retrieve console output from first instance up -- this will not work for non-nitro hypervisor VMs")
                logging.info(self.get_instance_console_output(first_new_instance)['Output'])
            except KeyError:
                logging.info("No output from instance yet. Trying again in 10 seconds.")
            sleep(10)

        # Wait for remaining instances (if any) to come up too
        while len(self.asgs_healthy_instances(new_asg)) < self.scale_to:
            logging.info("Waiting for all instances to be healthy ...")

        logging.info("ASG fully healthy. Logging new ASG name to \"new_asg.txt\"")
        open("new_asg.txt", "w").write(new_asg)

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

    def get_target_group_arn(self):
        """
        Returns a string containing the ARN of the target group supplied by --targetgroup or worked
        out by stepping through some logic from the loadbalancer from --lb
        """

        alb_client = aws_client.create_client('elbv2', self.region, self.role_arn)
        if self.target_group is not None:
            return alb_client.describe_target_groups(Names=[self.target_group])['TargetGroups'][0]['TargetGroupArn']

        loadbalancer_raw_info = alb_client.describe_load_balancers(Names=[self.loadbalancer])
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

    def get_launch_template_id(self, lt_name):
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

        # This is hackish because we are assuming that there is going to be only 1 (one) launch template
        return {
            "id": response['LaunchTemplates'][0]['LaunchTemplateId'],
            "version": response['LaunchTemplates'][0]['LatestVersionNumber']
        }

    def update_launch_template(self, inactive_asg, ami, lt_name):
        lt = self.get_launch_template_id(lt_name)
        lt_client  = aws_client.create_client('ec2', self.region, self.role_arn)

        lt_id = lt['id']
        lt_source_version = str(lt['version'])

        response = lt_client.create_launch_template_version(
            DryRun = False,
            LaunchTemplateId = lt_id,
            SourceVersion = lt_source_version,
            LaunchTemplateData = {
                "ImageId": ami
            }
        )

        launch_template_new_version = str(response['LaunchTemplateVersion']['VersionNumber'])

        lt_client.modify_launch_template(
            LaunchTemplateId=lt_id,
            DefaultVersion=launch_template_new_version
        )

        return {
            "id": lt_id,
            "version": launch_template_new_version
        }

    def scale(self, auto_scaling_group_id, min_size, max_size, capacity):
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)

        response = asg_client.update_auto_scaling_group(
            AutoScalingGroupName=auto_scaling_group_id,
            MinSize=min_size,
            MaxSize=max_size,
            DesiredCapacity=capacity
        )

        return response

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