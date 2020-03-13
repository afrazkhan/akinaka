#!/usr/bin/env python3

from akinaka.client.aws_client import AWS_Client
from akinaka.libs import exceptions
from akinaka.libs import helpers
import logging

aws_client = AWS_Client()

class TargetGroup():
    def __init__(self, region, role_arn, new_asg, log_level):
        self.region = region
        self.role_arn = role_arn
        self.new_asg = new_asg
        self.log_level = log_level
        logging.getLogger().setLevel(log_level)

    def get_application_name(self):
        asg_split = self.new_asg.split('-')[0:-1]

        return '-'.join(asg_split)

    def filter_out_unwanted_asgs(self, asgs, wanted_asg):
        """
        Takes a list of ASG objects (dicts), the ones you want to keep, and filters out everything else
        """

        return_list = []

        # Yes a regexp is smarter, but don't be smart, be safe ;)
        asg_split = wanted_asg.split('-')[0:-1]
        wanted_asg_prefix = '-'.join(asg_split)

        for asg in asgs:
            if wanted_asg_prefix in asg['AutoScalingGroupName']:
                return_list.append(asg)

        logging.debug("filter_out_unwanted_asgs(): Wanted ASG prefix: {}, Return list: {}".format(wanted_asg_prefix, return_list))

        return return_list

    def group_asgs_by_status(self, asgs, wanted_asg):
        """
        Returns a dict of 'active_asg' and 'inactive_asg' dicts with only the ASGs
        matching 'wanted_asgs'
        """

        inactive_asg = []
        active_asg = []

        for asg in asgs['AutoScalingGroups']:
            # If the ASG's TargetGroupARNs attribute is empty, it's the inactive one
            if len(asg['TargetGroupARNs']) < 1 and asg['AutoScalingGroupName'] == self.new_asg:
                inactive_asg.append(asg)

            # If the ASG's TargetGroupARNs attribute is not empty, it's the active one
            elif len(asg['TargetGroupARNs']) > 0:
                active_asg.append(asg)

        active_asg = self.filter_out_unwanted_asgs(active_asg, wanted_asg)
        inactive_asg = self.filter_out_unwanted_asgs(inactive_asg, wanted_asg)

        logging.debug("group_asgs_by_status(): active_asg: {}, inactive_asg: {} ".format(active_asg, inactive_asg))

        return {'active_asg': active_asg, 'inactive_asg': inactive_asg}

    def switch_asg(self):
        target_group_arns = []
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        elb_client = aws_client.create_client('elbv2', self.region, self.role_arn)
        elb_waiter = elb_client.get_waiter('target_in_service')
        asgs = asg_client.describe_auto_scaling_groups()

        asgs_by_status = self.group_asgs_by_status(asgs, self.new_asg)
        active_asg = asgs_by_status['active_asg']
        inactive_asg = asgs_by_status['inactive_asg']

        logging.debug("switch_asg(): asgs_by_status: {}, active_asg: {}, inactive_asg: {}".format(asgs_by_status, active_asg, inactive_asg))

        # Exit program if there is no existing active auto scaling groups to perform a switch over
        if len(inactive_asg) < 1 or len(active_asg) < 1:
            raise exceptions.AkinakaCriticalException('No auto scaling groups are available for this switch over.')

        # Get the target group ARNs from the active auto scaling group
        target_group_arns = active_asg[0]['TargetGroupARNs']

        # Get the instance IDs from the inactive auto scaling group
        inactive_asg_instances = []
        for instance in inactive_asg[0]['Instances']:
            inactive_asg_instances.append(dict(Id=instance['InstanceId']))

        # Add the ASG to the target group ARNs
        try:
            for asg in inactive_asg:
                asg_client.attach_load_balancer_target_groups(
                    AutoScalingGroupName=asg['AutoScalingGroupName'],
                    TargetGroupARNs=target_group_arns
                )
        except Exception as e:
            logging.error("Couldn't attach the new ASG {} to the target group {}".format(inactive_asg, target_group_arns))
            logging.error(e)
            # FIXME: Raise an exception.AkinakaCriticalException above instead of catching this
            exit(1)

        # Check if the newly attached instances are reported healthy in the target group before detaching the old ASG
        try:
            elb_waiter.wait(TargetGroupArn=target_group_arns, Targets=inactive_asg_instances)
        except Exception as e:
            logging.error("One or more instances from the new ASG {} are not InService to the target group {}".format(inactive_asg, target_group_arns))
            logging.error(e)
            # FIXME: Raise an exception.AkinakaCriticalException above instead of catching this
            exit(1)
        else:
            logging.info("The instances from the {} ASG became InService in the target group.".format(inactive_asg))

        # Remove the asg from the target group
        try:
            for asg in active_asg:
                asg_client.detach_load_balancer_target_groups(
                    AutoScalingGroupName=asg['AutoScalingGroupName'],
                    TargetGroupARNs=target_group_arns
                )
        except Exception as e:
            logging.error("Couldn't attach the new ASG {} to the target group {}".format(inactive_asg, target_group_arns))
            logging.error(e)
            # FIXME: Raise an exception.AkinakaCriticalException above instead of catching this
            exit(1)

        return
