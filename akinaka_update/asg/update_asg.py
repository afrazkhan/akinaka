#!/usr/bin/env python3

from time import sleep
from akinaka_client.aws_client import AWS_Client

aws_client = AWS_Client()

class ASG():
    def __init__(self, ami, region, role_arn, loadbalancer=None, asg=None, target_group=None):
        self.loadbalancer = loadbalancer
        self.ami = ami
        self.region = region
        self.role_arn = role_arn
        self.asg = asg
        self.target_group = target_group

    def do_update(self):
        target_groups = None
        new_ami = self.ami

        if self.asg is not None:
            new_asg = self.asg
        elif self.loadbalancer is not None and self.target_group is None:
            target_groups = self.get_lb_target_groups()
        elif self.loadbalancer is None and self.target_group is not None:
            target_groups = [self.get_target_group_arn(self.target_group)]
        else:
            print("""
            One of these mutually exclusive options need to be passed:
               --lb
               --asg
               --target-groups
            """)
            exit(1)

        if target_groups is not None:
            these_current_asg_instances = self.current_asg_instances(target_groups)
            new_asg = self.get_inactive_asg(these_current_asg_instances)

        try:
            self.update_launch_template(new_asg, new_ami, self.get_lt_name(new_asg))
            self.update_asg(new_asg, 1, 1, 1)
            open("new_asg.txt", "w").write(new_asg)
        except Exception as e:
            print("Didn't update the ASG {}, because: {}".format(new_asg, e))
            exit(1)


    def get_lt_name(self, asg):
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        lt_info = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg])

        return lt_info['AutoScalingGroups'][0]['LaunchTemplate']['LaunchTemplateName']

    def get_lb_target_groups(self):
        alb_client = aws_client.create_client('elbv2', self.region, self.role_arn)

        loadbalancer_raw_info = alb_client.describe_load_balancers(Names=[self.loadbalancer])
        loadbalancer_arn = loadbalancer_raw_info['LoadBalancers'][0]['LoadBalancerArn']

        target_groups_raw_info = alb_client.describe_target_groups(LoadBalancerArn=loadbalancer_arn)['TargetGroups']
        target_group_arns = [targetgroup['TargetGroupArn'] for targetgroup in target_groups_raw_info]

        return target_group_arns

    def get_target_group_arn(self, target_group):
        alb_client = aws_client.create_client('elbv2', self.region, self.role_arn)        
        return alb_client.describe_target_groups(Names=[target_group])['TargetGroups'][0]['TargetGroupArn']

    def get_target_groups_instances(self, target_group_arns):
        alb_client = aws_client.create_client('elbv2', self.region, self.role_arn)
        
        target_groups_instances = []

        for arn in target_group_arns:
            target_group_instances = alb_client.describe_target_health(TargetGroupArn=arn)['TargetHealthDescriptions']

            for instance in target_group_instances:
                if instance['TargetHealth']['State'] == 'healthy':
                    target_groups_instances.append(instance['Target']['Id'])
        
        return target_groups_instances 

    def current_asg_instances(self, target_groups):
        ec2_client = aws_client.create_client('ec2', self.region, self.role_arn)
        
        if self.target_group is not None:
            target_groups = [self.get_target_group_arn(self.target_group)]
        else:
            target_groups = self.get_lb_target_groups()

        target_groups_instances = self.get_target_groups_instances(target_groups)
        instances_with_tags = {}

        #get autoscaling groups from instances
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


        return instances_with_asg

    def get_inactive_asg(self, instances_with_asgs):
        active_asg = next(iter(instances_with_asgs.values()))
        asg_parts = active_asg.split(active_asg[2])

        asg_generic_name = "{}-{}".format(asg_parts[0], asg_parts[1])
        active_colour = asg_parts[2]

        if active_colour == "blue":
            inactive_colour = "green"
        else:
            inactive_colour = "blue"

        inactive_asg_name = "{}-{}".format(asg_generic_name, inactive_colour)

        return inactive_asg_name

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

    def update_asg(self, auto_scaling_group_id, min_size, max_size, capacity):
        # Get a list of active instances from the auto scaling group
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)

        # Scale down
        response = asg_client.update_auto_scaling_group(
            AutoScalingGroupName=auto_scaling_group_id,
            MinSize=0,
            MaxSize=0,
            DesiredCapacity=0
        )

        while len(self.get_auto_scaling_group_status(auto_scaling_group_id)) > 0:
            sleep(60)

        # Scale up
        response = asg_client.update_auto_scaling_group(
            AutoScalingGroupName=auto_scaling_group_id,
            MinSize=min_size,
            MaxSize=max_size,
            DesiredCapacity=capacity
        )

        while len(self.get_auto_scaling_group_status(auto_scaling_group_id)) < 1:
            sleep(10)

        return response

    def get_auto_scaling_group_status(self, auto_scaling_group_id):
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        asg_instances = asg_client.describe_auto_scaling_instances()
        target_instances = []

        for i in asg_instances['AutoScalingInstances']:
            if i['AutoScalingGroupName'] == auto_scaling_group_id and i['LifecycleState'] == "InService":
                target_instances.append(i)

                print("Instance {instance_id} has state = {instance_state}\n"
                    "Lifecycle is at {instance_lifecycle_state}".format(
                        instance_id = i['InstanceId'],
                        instance_state = i['HealthStatus'],
                        instance_lifecycle_state = i['LifecycleState']
                )
            )

        return target_instances
