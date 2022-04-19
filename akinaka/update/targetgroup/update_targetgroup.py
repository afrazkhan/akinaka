#!/usr/bin/env python3

from akinaka.client.aws_client import AWS_Client
from akinaka.libs import exceptions
import botocore.exceptions
import logging

aws_client = AWS_Client()

class TargetGroup():
    """ TODO """

    def __init__(self, region, role_arn, new_asg, traffic_policy_requests, log_level):
        self.region = region
        self.role_arn = role_arn
        self.new_asg = new_asg
        self.traffic_policy_requests = traffic_policy_requests
        self.log_level = log_level
        logging.getLogger().setLevel(log_level)

    def get_application_name(self):
        """ TODO """

        asg_split = self.new_asg.split('-')[0:-1]

        return '-'.join(asg_split)

    @staticmethod
    def sanity_checks(new_asgs, current_asgs):
        """ Perform some critical checks on the state of the ASGs """

        # Exit program if there is no existing active auto scaling groups to perform a switch over
        if len(new_asgs) < 1 or len(current_asgs) < 1:
            raise exceptions.AkinakaCriticalException('No auto scaling groups are available for this switch over')

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

        logging.debug(f"filter_out_unwanted_asgs(): Wanted ASG prefix: {wanted_asg_prefix}, Return list: {return_list}")

        return return_list

    def group_asgs_by_status(self, asgs, wanted_asg):
        """
        Returns a dict of 'current_asg' and 'new_asg' dicts with only the ASGs
        matching 'wanted_asgs'
        """

        new_asg = []
        current_asg = []

        for asg in asgs['AutoScalingGroups']:
            # If the ASG's TargetGroupARNs attribute is empty, it's the new one
            if len(asg['TargetGroupARNs']) < 1 and asg['AutoScalingGroupName'] == self.new_asg:
                new_asg.append(asg)

            # If the ASG's TargetGroupARNs attribute is not empty, it's the active one
            elif len(asg['TargetGroupARNs']) > 0:
                current_asg.append(asg)

        current_asg = self.filter_out_unwanted_asgs(current_asg, wanted_asg)
        new_asg = self.filter_out_unwanted_asgs(new_asg, wanted_asg)

        logging.debug("group_asgs_by_status(): current_asg: {current_asg}, new_asg: {new_asg} ")

        return {'current_asg': current_asg, 'new_asg': new_asg}

    def deregister_targets(self, asgs, target_group_arn):
        """ Remove [instance_ids] from [target_group_arns[0]] so the ASG can be detached """

        elb_client = aws_client.create_client('elbv2', self.region, self.role_arn)
        elb_waiter = elb_client.get_waiter('target_deregistered')

        for this_asg in asgs:
            asg_name = this_asg['AutoScalingGroupName']

            instance_ids = []
            for instance in this_asg['Instances']:
                instance_ids.append(dict(Id=instance['InstanceId']))

            logging.info(f"Deregistering the following instances from the target group before detaching {asg_name}:\n{instance_ids}")

            targets = []

            for this_instance in instance_ids:
                this_instance.update({'Port': 443})
                targets.append(this_instance)

            elb_client.deregister_targets(
                TargetGroupArn=target_group_arn[0],
                Targets=targets
            )

            try:
                elb_waiter.wait(
                    TargetGroupArn=target_group_arn[0],
                    Targets=targets
                )
            except botocore.exceptions.WaiterError as e:
                logging.error(f"There was a problem deregistering instances:\n{e}")
                exit(1)

            logging.info(f"Successfully deregistered old ASG instances for {asg_name}")

    def get_asg_policies(self, asg):
        """ Returns the scaling policies of [asg] """

        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        response = asg_client.describe_policies(AutoScalingGroupName=asg)

        return response

    def add_traffic_asg_policy(self, asgs, target_group_arn, traffic_policy_requests=None):
        """
        Attaches a scaling policy to [asgs][*] to maintain an average number of requests
        of [traffic_policy_requests] per instance
        """

        traffic_policy_requests = traffic_policy_requests or 50.0
        if traffic_policy_requests == 0: # Disable the traffic policy if we're passed 0 for requests
            return True

        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        alb_client = aws_client.create_client('elbv2', self.region, self.role_arn)

        load_balancers = alb_client.describe_target_groups(TargetGroupArns=[target_group_arn])['TargetGroups'][0]['LoadBalancerArns'][0]
        load_balancer_part = load_balancers.split(':')[-1].replace('loadbalancer/', '')

        for this_asg in asgs:
            try:
                asg_name = this_asg['AutoScalingGroupName']
                logging.info(f"Adding the 'RequestScaling' scaling policy to {asg_name}")
                load_balancer_target_group = asg_client.describe_load_balancer_target_groups(AutoScalingGroupName=asg_name)['LoadBalancerTargetGroups'][0]['LoadBalancerTargetGroupARN']
                target_group_part = load_balancer_target_group.split((':'))[-1]

                resource_label = f"{load_balancer_part}/{target_group_part}"
                logging.debug(f"Resource label worked out as: {resource_label}")
                logging.debug(f"ASG worked out as: {asg_name}")

                asg_client.put_scaling_policy(
                    AutoScalingGroupName=asg_name,
                    PolicyName='RequestScaling',
                    PolicyType='TargetTrackingScaling',
                    EstimatedInstanceWarmup=60,
                    TargetTrackingConfiguration={
                      'PredefinedMetricSpecification': {
                        'PredefinedMetricType': 'ALBRequestCountPerTarget',
                        'ResourceLabel': resource_label
                      },
                      'TargetValue': float(traffic_policy_requests),
                      'DisableScaleIn': False
                    },
                    Enabled=True
                )
            except botocore.exceptions.ClientError as error:
                logging.error(f"Couldn't add the scaling policy because: {error}")

    def remove_traffic_asg_policy(self, asgs):
        """ Remove the policy called "RequestScaling" added by self.add_traffic_asg_policy """

        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)

        try:
            for this_asg in asgs:
                asg_name = this_asg['AutoScalingGroupName']
                logging.info(f"Removing the 'RequestScaling' scaling policy from {asg_name}")
                asg_client.delete_policy(AutoScalingGroupName=asg_name, PolicyName='RequestScaling')
        except botocore.exceptions.ClientError as error:
            logging.warning(f"Couldn't remove the scaling policy named 'RequestScaling': {error}")

    def check_asg_instances(self, asgs):
        """
        Ensure that [asgs] actually has at least some healthy instances running in it
        """

        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)

        for this_asg in asgs:
            asg_name = this_asg['AutoScalingGroupName']

            logging.info(f"Checking the instances of ASG {asg_name}")
            instances = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])['AutoScalingGroups'][0]['Instances']

            try:
                for this_instance in instances:
                    if this_instance['HealthStatus'] != 'Healthy':
                        raise exceptions.AkinakaCriticalException("One or more of the instances in the new ASG is not healthy")
            except KeyError as e:
                raise exceptions.AkinakaCriticalException(f"It's possible that there are no instances in the new ASG {asg_name}: {e}")

            if len(instances) == 0:
                raise exceptions.AkinakaCriticalException("One or more of the instances in the new ASG is not healthy")

            logging.info(f"{asg_name} has instances that report themselves as healthy")

    def wait_for_healthy_attachment(self, asgs, target_group_arns):
        """
        Wait until all instances in [asg] are reporting a healthy status in
        in [target_group]
        """

        elb_client = aws_client.create_client('elbv2', self.region, self.role_arn)
        elb_waiter = elb_client.get_waiter('target_in_service')

        asg_instances = []
        for this_asg in asgs:
            asg_name = this_asg['AutoScalingGroupName']

            for instance in this_asg['Instances']:
                asg_instances.append(dict(Id=instance['InstanceId']))

            logging.info(f"Waiting for the instances from the {asg_name} ASG to become Healthy targets")
            for tg in target_group_arns:
                try:
                    elb_waiter.wait(TargetGroupArn=tg, Targets=asg_instances)
                except IndexError as e:
                    logging.error(f"Some of them did not register as Healthy:\n{e}")
                    logging.error(elb_client.describe_target_health(TargetGroupArn=tg, Targets=asg_instances))
                    raise exceptions.AkinakaCriticalException("""
                    New ASG instances failed during a deploy, you will need to decide whether you want
                    to detach them. Please take a look at the pipelines right now
                    """)
                else:
                    logging.info(f"All instances in new ASG {asg_name} reported as healthy")

    def add_asgs_to_target_group(self, asgs, target_group_arns):
        """ Add the ASG to the target group ARNs """

        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)

        for this_asg in asgs:
            try:
                asg_name = this_asg['AutoScalingGroupName']
                logging.info(f"Attaching the {asg_name} ASG to the target group...")

                asg_client.attach_load_balancer_target_groups(
                    AutoScalingGroupName=asg_name,
                    TargetGroupARNs=target_group_arns
            )
            except Exception as e:
                logging.error(f"Couldn't attach the new {asg_name} ASG to the {target_group_arns} target group!")
                logging.error(e)
                # FIXME: Raise an exceptions.AkinakaCriticalException above instead of catching this
                exit(1)
            else:
                logging.info(f"Successfully attached {asg_name} to {target_group_arns}")

    def detatch_asg_from_target_group(self, asgs, target_group_arns):
        """ Detach [asg] from [target_group_arns] """

        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)

        for this_asg in asgs:
            asg_name = this_asg['AutoScalingGroupName']

            logging.info(f"Detaching the {asg_name} ASG from the target group")
            try:
                asg_client.detach_load_balancer_target_groups(
                    AutoScalingGroupName=asg_name,
                    TargetGroupARNs=target_group_arns
                )
            except Exception as e:
                logging.error(f"Could not detach {asg_name} ASG from the {target_group_arns} target group")
                logging.error(e)
                # FIXME: Raise an exception.AkinakaCriticalException above instead of catching this
                exit(1)
            else:
                logging.info(f"Detached {asg_name} from {target_group_arns}")

    def scale_down_asg(self, asgs):
        """ Scale down [asg] to a min, max, desired of 0,0,0 """

        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)

        for this_asg in asgs:
            try:
                asg_name = this_asg['AutoScalingGroupName']
                logging.info(f"Scaling down {asg_name} to 0")
                asg_client.update_auto_scaling_group(
                    AutoScalingGroupName=asg_name,
                    MinSize=0,
                    MaxSize=0,
                    DesiredCapacity=0
                )
            except Exception as e:
                logging.error(f"Could not scale down the old {asg_name} ASG")
                logging.error(e)
                # FIXME: Raise an exception.AkinakaCriticalException above instead of catching this
                exit(1)
            else:
                logging.info(f"Scaled down {asg_name} to 0")

    def main(self, keep_old_asg=False):
        """
        Runs class methods needed to switch the target group over to [self.new_asg]
        """

        target_group_arns = []
        asg_client = aws_client.create_client('autoscaling', self.region, self.role_arn)
        asgs = asg_client.describe_auto_scaling_groups()

        asgs_by_status = self.group_asgs_by_status(asgs, self.new_asg)
        current_asgs = asgs_by_status['current_asg']
        new_asgs = asgs_by_status['new_asg']

        logging.debug(f"main(): asgs_by_status: {asgs_by_status}, current_asg: {current_asgs}, new_asg: {new_asgs}")

        self.sanity_checks(new_asgs, current_asgs)

        # Get the target group ARNs from the current auto scaling group
        target_group_arns = current_asgs[0]['TargetGroupARNs']

        # Ensure the new ASG is in a good state before proceeding
        self.check_asg_instances(new_asgs)

        # Add the ASG to the target group ARNs
        self.add_asgs_to_target_group(new_asgs, target_group_arns)

        # Check if the newly attached instances are reported healthy in the target group before detaching the old ASG
        self.wait_for_healthy_attachment(new_asgs, target_group_arns)

        # Add a policy to the new ASG to scale on traffic
        self.add_traffic_asg_policy(new_asgs, target_group_arns[0], self.traffic_policy_requests)

        # De-register the (now old) current ASG targets
        self.deregister_targets(current_asgs, target_group_arns)

        # We have to remove the traffic policy before removing the ASG
        self.remove_traffic_asg_policy(current_asgs)

        # Remove the asg from the target group
        self.detatch_asg_from_target_group(current_asgs, target_group_arns)

        # Scale down the old (detached) ASG to 0/0/0
        if not keep_old_asg:
            self.scale_down_asg(current_asgs)

        return True
