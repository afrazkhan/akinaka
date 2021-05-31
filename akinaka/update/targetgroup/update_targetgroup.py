#!/usr/bin/env python3

from akinaka.client.aws_client import AWS_Client
from akinaka.libs import exceptions
import botocore.exceptions
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
            if wanted_asg_prefix == asg['AutoScalingGroupName'][:asg['AutoScalingGroupName'].rfind('-')]:
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

    def deregister_old_targets(self, instance_ids, target_group_arn):
        """ Remove [instance_ids] from [target_group_arn] so the ASG can be detached """

        elb_client = aws_client.create_client('elbv2', self.region, self.role_arn)
        elb_waiter = elb_client.get_waiter('target_deregistered')

        targets = []

        for this_instance in instance_ids:
            this_instance.update({'Port': 443})
            targets.append(this_instance)

        elb_client.deregister_targets(
            TargetGroupArn=target_group_arn,
            Targets=targets
        )

        try:
            elb_waiter.wait(
                TargetGroupArn=target_group_arn,
                Targets=targets
            )
        except botocore.exceptions.WaiterError as e:
            logging.error(f"There was a problem deregistering instances:\n{e}")
            exit(1)

        logging.info("Successfully deregistered old ASG instances, moving on to detachment of the ASG itself")

    def main(self, scale_down_inactive=False):
        target_group_arns = []
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        elb_client = aws_client.create_client('elbv2', self.region, self.role_arn)
        elb_waiter = elb_client.get_waiter('target_in_service')
        asgs = asg_client.describe_auto_scaling_groups()

        asgs_by_status = self.group_asgs_by_status(asgs, self.new_asg)
        active_asg = asgs_by_status['active_asg']
        inactive_asg = asgs_by_status['inactive_asg']
        inactive_asg_name = inactive_asg[0]['AutoScalingGroupName']
        active_asg_name = active_asg[0]['AutoScalingGroupName']

        logging.debug("main(): asgs_by_status: {}, active_asg: {}, inactive_asg: {}".format(asgs_by_status, active_asg, inactive_asg))

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
        logging.info(f"Attaching the {inactive_asg_name} ASG to the target group...")
        try:
            for asg in inactive_asg:
                asg_client.attach_load_balancer_target_groups(
                    AutoScalingGroupName=asg['AutoScalingGroupName'],
                    TargetGroupARNs=target_group_arns
                )
        except Exception as e:
            logging.error(f"Couldn't attach the new {inactive_asg_name} ASG to the {target_group_arns} target group!")
            logging.error(e)
            # FIXME: Raise an exception.AkinakaCriticalException above instead of catching this
            exit(1)
        else:
            logging.info(f"Successfully attached {inactive_asg} to {target_group_arns}")

        # Check if the newly attached instances are reported healthy in the target group before detaching the old ASG
        logging.info(f"Waiting for the instances from the {inactive_asg_name} ASG to become Healthy targets")
        for tg in target_group_arns:
            try:
                elb_waiter.wait(TargetGroupArn=tg, Targets=inactive_asg_instances)
            except Exception as e:
                logging.error("Some of them did not register as Healthy. Check/Detach them manually. Quiting")
                logging.error(e)
                # FIXME: Raise an exception.AkinakaCriticalException above instead of catching this
                exit(1)
            else:
                logging.info(f"All instances in new ASG {inactive_asg_name} reported as healthy")

        # Get the instance IDs from the (old) active auto scaling group
        old_asg_instances = []
        for instance in active_asg[0]['Instances']:
            old_asg_instances.append(dict(Id=instance['InstanceId']))

        # Deregister old instances before detaching the old ASG
        logging.info(f"Deregistering the following instances from the target group before detaching {active_asg_name}:\n{old_asg_instances}")
        self.deregister_old_targets(old_asg_instances, target_group_arns[0])

        # Remove the asg from the target group
        logging.info(f"Detaching the {active_asg_name} ASG from the target group")
        try:
            for asg in active_asg:
                asg_client.detach_load_balancer_target_groups(
                    AutoScalingGroupName=asg['AutoScalingGroupName'],
                    TargetGroupARNs=target_group_arns
                )
        except Exception as e:
            logging.error(f"Could not detach the old {inactive_asg} ASG from the {target_group_arns} target group!")
            logging.error(e)
            # FIXME: Raise an exception.AkinakaCriticalException above instead of catching this
            exit(1)
        else:
            logging.info(f"Detached {inactive_asg} from {target_group_arns}")

        if scale_down_inactive:
            # Scale down the old (detached) ASG to 0/0/0
            logging.info(f"Scaling down {active_asg_name} to 0")
            try:
                for asg in active_asg:
                    asg_client.update_auto_scaling_group(
                        AutoScalingGroupName=asg['AutoScalingGroupName'],
                        MinSize=0,
                        MaxSize=0,
                        DesiredCapacity=0
                    )
            except Exception as e:
                logging.error(f"Could not scale down the old {inactive_asg} ASG")
                logging.error(e)
                # FIXME: Raise an exception.AkinakaCriticalException above instead of catching this
                exit(1)
            else:
                logging.info(f"Scaled down {active_asg_name} to 0")

        return
