#!/usr/bin/env python3

from akinaka_client.aws_client import AWS_Client

aws_client = AWS_Client()

class TargetGroup():
    def __init__(self, region, role_arn, new_asg):
        self.region = region
        self.role_arn = role_arn
        self.new_asg = new_asg

    def switch_asg(self):
        target_group_arns = []
        inactive_asg = []
        active_asg = []
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        auto_scaling_groups = asg_client.describe_auto_scaling_groups()

        for asg in auto_scaling_groups['AutoScalingGroups']:
            # If the ASG's TargetGroupARNs attribute is empty, it's the inactive one
            if len(asg['TargetGroupARNs']) < 1 and asg['AutoScalingGroupName'] == self.new_asg:
                inactive_asg.append(asg)

            # If the ASG's TargetGroupARNs attribute is not empty, it's the active one
            elif len(asg['TargetGroupARNs']) > 0:
                active_asg.append(asg)

        # Exit program if there is no existing active auto scaling groups to perform a switch over\
        if len(inactive_asg) < 1 or len(active_asg) < 1:
            print('No auto scaling groups are available for this switch over.')
            exit(1)

        # Get the target group ARNs from the active auto scaling group
        for arn in active_asg:
            target_group_arns = arn['TargetGroupARNs']

        # Add the asg (http, https) to the target group ARNs
        # https://docs.aws.amazon.com/cli/latest/reference/autoscaling/attach-load-balancer-target-groups.html
        for asg in inactive_asg:
            asg_client.attach_load_balancer_target_groups(
                AutoScalingGroupName=asg['AutoScalingGroupName'],
                TargetGroupARNs=target_group_arns
            )

        # Remove the asg (http, https) from the target group
        # https://docs.aws.amazon.com/cli/latest/reference/autoscaling/detach-load-balancer-target-groups.html
        for asg in active_asg:
            asg_client.detach_load_balancer_target_groups(
                AutoScalingGroupName=asg['AutoScalingGroupName'],
                TargetGroupARNs=target_group_arns
            )

        return
