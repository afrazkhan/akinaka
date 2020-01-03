# Akinaka

This is a general all-purpose tool for managing things in AWS that Terraform is not responsible for -- you can think of it as an extension to the `aws` CLI.

At the moment it only does three things; blue/green deploys for plugging into Gitlab, AMI cleanups, and RDS copies to other accounts.

- [Akinaka](#akinaka)
  - [Installation](#installation)
  - [Requirements and Presumptions](#requirements-and-presumptions)
  - [A Note on Role Assumption](#a-note-on-role-assumption)
  - [Deploys](#deploys)
  - [Cleanups](#cleanups)
    - [AMIs](#amis)
    - [EBS Volumes](#ebs-volumes)
    - [RDS Snapshots](#rds-snapshots)
  - [RDS](#rds)
    - [Copy](#copy)
  - [Disaster Recovery](#disaster-recovery)
    - [Transfer](#transfer)
  - [Container](#container)
  - [Billing](#billing)
  - [Contributing](#contributing)

## Installation

    pip3 install akinaka

## Requirements and Presumptions

Format of ASG names: "whatever-you-like*-blue/green*" — the part in bold is necessary, i.e. you must have two ASGs, one ending with "-blue" and one ending with "-green".

The following permissions are necessary for the IAM role / user that will be running Akinaka:

    sts:AssumeRole

_NOTE: Going forward, IAM policies will be listed separately for their respective subcommands (as is already the case for [Transfer](#transfer)). For now however, the following single catch-all policy can be used, attach it to the IAM profile that Akinaka will be assuming:_

    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "2018121701",
                "Effect": "Allow",
                "Action": [
                    "ec2:AuthorizeSecurityGroupIngress",
                    "ec2:DescribeInstances",
                    "ec2:CreateKeyPair",
                    "ec2:CreateImage",
                    "ec2:CopyImage",
                    "ec2:DescribeSnapshots",
                    "elasticloadbalancing:DescribeLoadBalancers",
                    "ec2:DeleteVolume",
                    "ec2:ModifySnapshotAttribute",
                    "autoscaling:DescribeAutoScalingGroups",
                    "ec2:DescribeVolumes",
                    "ec2:DetachVolume",
                    "ec2:DescribeLaunchTemplates",
                    "ec2:CreateTags",
                    "ec2:RegisterImage",
                    "autoscaling:DetachLoadBalancerTargetGroups",
                    "ec2:RunInstances",
                    "ec2:StopInstances",
                    "ec2:CreateVolume",
                    "autoscaling:AttachLoadBalancerTargetGroups",
                    "elasticloadbalancing:DescribeLoadBalancerAttributes",
                    "ec2:GetPasswordData",
                    "elasticloadbalancing:DescribeTargetGroupAttributes",
                    "elasticloadbalancing:DescribeAccountLimits",
                    "ec2:DescribeImageAttribute",
                    "elasticloadbalancing:DescribeRules",
                    "ec2:DescribeSubnets",
                    "ec2:DeleteKeyPair",
                    "ec2:AttachVolume",
                    "autoscaling:DescribeAutoScalingInstances",
                    "ec2:DeregisterImage",
                    "ec2:DeleteSnapshot",
                    "ec2:DescribeRegions",
                    "ec2:ModifyImageAttribute",
                    "elasticloadbalancing:DescribeListeners",
                    "ec2:CreateSecurityGroup",
                    "ec2:CreateSnapshot",
                    "elasticloadbalancing:DescribeListenerCertificates",
                    "ec2:ModifyInstanceAttribute",
                    "elasticloadbalancing:DescribeSSLPolicies",
                    "ec2:TerminateInstances",
                    "elasticloadbalancing:DescribeTags",
                    "ec2:DescribeTags",
                    "ec2:DescribeLaunchTemplateVersions",
                    "ec2:DescribeSecurityGroups",
                    "ec2:DescribeImages",
                    "ec2:DeleteSecurityGroup",
                    "elasticloadbalancing:DescribeTargetHealth",
                    "elasticloadbalancing:DescribeTargetGroups"
                ],
                "Resource": "*"
            },
            {
                "Sid": "2018121702",
                "Effect": "Allow",
                "Action": [
                    "ssm:PutParameter",
                    "ssm:GetParameter",
                    "autoscaling:UpdateAutoScalingGroup",
                    "ec2:ModifyLaunchTemplate",
                    "ec2:CreateLaunchTemplateVersion",
                    "autoscaling:AttachLoadBalancerTargetGroups"
                ],
                "Resource": [
                    "arn:aws:autoscaling:*:*:autoScalingGroup:*:autoScalingGroupName/*",
                    "arn:aws:ssm:eu-west-1:[YOUR_ACCOUNT]:parameter/deploying-status-*",
                    "arn:aws:ec2:*:*:launch-template/*"
                ]
            }
        ]
    }

## A Note on Role Assumption

Akinaka uses IAM roles to gain access into multiple accounts. Most commands require you to specify a list of roles you wish to perform a task for, and that role must have the [sts:AssumeRole](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_temp_control-access_enable-create.html) permission. This is not only good security, it's helpful for ensuring you're doing things to the accounts you think you're doing things for ;)

## Deploys

Done with the `update` parent command, and then the `asg` and `targetgroup` subcommands (`update targetgroup` is only needed for blue/green deploys).

Example:

    # For standalone ASGs (not blue/green)
    akinaka update \
      --region eu-west-1 \
      --role-arn arn:aws:iam::123456789100:role/management_assumable \
    asg \
      --asg workers \
      --ami ami-000000

    # For blue/green ASGs
    akinaka update \
      --region eu-west-1 \
      --role-arn arn:aws:iam::123456789100:role/management_assumable \
    asg \
      --lb lb-asg-ext \
      --ami ami-000000

    # For blue/green ASGs with multiple Target Groups behind the same ALB
    akinaka update \
      --region eu-west-1 \
      --role-arn arn:aws:iam::123456789100:role/management_assumable \
    asg \
      --target-group application-1a \
      --ami ami-000000

For blue/green deploys, the next step is to check the health of your new ASG.
For the purposes of Gitlab CI/CD pipelines, this will be printed out as the only
output, so that it can be used in the next job.

Once the new ASG is confirmed to be working as expected:

    akinaka update --region eu-west-1 --role-arn arn:aws:iam::123456789100:role/management_assumable asg --new blue

The value of `--role-arn` is used to assume a role in the target account with enough
permissions to perform the actions of modifying ASGs and Target Groups. As such,
`akinaka` is able to do cross-account deploys. It will deliberately error if you
do not supply an IAM Role ARN, in order to ensure you are deploying to the account
you think you are.

## Cleanups

Currently AMI, EBS, and RDS snapshot cleanups are supported.

Common option:

`--role-arns` is a space separated list of IAM ARNs that can be assumed by the token you are using
to run this command. The AMIs for the running instances found in these accounts will not be deleted. Not to be confused with `--role-arn`, accepted for the `update` parent command, for deploys.

### AMIs

Cleans up AMIs and their snapshots based on a specified retention period, and deduced AMI usage (will
not delete AMIs that are currently in use). You can optionally specify an AMI name pattern, and it will
keep the latest version of all the AMIs it finds for it.

Usage:

    akinaka cleanup \
        --region eu-west-1 \
        --role-arns "arn:aws:iam::198765432100:role/management_assumable arn:aws:iam::123456789100:role/management_assumable" \
        ami \
            --exceptional-amis cib-base-image-*
            --retention 7

The above will delete all AMIs and their snapshots, _except for those which:_

1. Are younger than 7 days AND
2. Are not in use by AWS accounts "123456789100" or "198765432100" AND
3. WHERE the AMI name matches the pattern "cib-base-image-*", there is more than one match AND it is the oldest one

`--exceptional-amis` is a space seperated list of exact names or patterns for which to keep the latest
version of an AMI for. For example, the pattern "cib-base-image-*" will match with normal globbing, and
if there is more than one match, only the latest one will not be deleted (else there is no effect).

`--retention` is the retention period you want to exclude from deletion. For example; `--retention 7`
will keep all AMIs found within 7 days, if they are not in the `--exceptional-amis` list.

### EBS Volumes

Delete all EBS volumes that are not attached to an instance (stopped or not):

    akinaka cleanup \
        --region eu-west-1 \
        --role-arns "arn:aws:iam::198765432100:role/management_assumable arn:aws:iam::123456789100:role/management_assumable" \
        ebs

### RDS Snapshots

    This will delete all snapshots tagged "akinaka-made":
    
    akinaka cleanup \
        --not-dry-run \
        --region eu-west-1 \
        --role-arns "arn:aws:iam::876521782800:role/OlinDataAssumedAdministrator" \
        rds \
            --tags "akinaka-made"

## RDS

Perform often necessary but complex tasks with RDS.

### Copy

Copy encrypted RDS instances between accounts:

    akinaka copy --region eu-west-1 \
        rds \
            --source-role-arn arn:aws:iam::198765432100:role/management_assumable \
            --target-role-arn arn:aws:iam::123456789100:role/management_assumable \
            --snapshot-style running_instance \
            --source-instance-name DB_FROM_ACCOUNT_198765432100 \
            --target-instance-name DB_FROM_ACCOUNT_123456789100 \
            --target-security-group SECURITY_GROUP_OF_TARGET_RDS \
            --target-db-subnet SUBNET_OF_TARGET_RDS \

`--region` is optional because it will default to the environment variable `AWS_DEFAULT_REGION`.

## Disaster Recovery

Akinaka has limited functionality for backing up and restoring data for use in disaster recovery.

### Transfer

Transfer data from S3, RDS, and RDS Aurora into a backup account:

    akinaka dr \
      --region eu-west-1 \
      --source-role-arn arn:aws:iam::[LIVE_ACCOUNT_ID]:role/[ROLE_NAME] \
      --destination-role-arn arn:aws:iam::[BACKUP_ACCOUNT_ID]:role/[ROLE_NAME] \
      transfer \
        --service s3

Omitting `--service` will include all supported services.

You can optionally specify the name of the instance to transfer with `--names` in a comma separated list, e.g. `--names 'database-1, database-2`. This can be for either RDS instances, or S3 buckets, but not both at the same time. Future versions may remove `--service` and replace it with a subcommand instead, i.e. `akinaka dr transfer rds`, so that those service can have `--names` to themselves.

A further limitation is that only a single region can be handled at a time for S3 buckets. If you wish to backup all S3 buckets in an account, and they are in different regions, you will have to specify them per run, using the appropriate region each time. Future versions will work the bucket regions out automatically, and remove this limitation.

Akinaka must be run from either an account or instance profile which can use sts:assume to assume both the `source-role-arn` and `destination-role-arn`. This is true even if you are running on the account that `destination-role-arn` is on. You will therefore need this policy attached to the user/role that's doing the assuming:

    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "akinakaassume",
                "Effect": "Allow",
                "Action": "sts:AssumeRole",
                "Resource": [
                    "arn:aws:iam::[DESTINATION_ACCOUNT]:role/[ROLE_TO_ASSUME]",
                    "arn:aws:iam::[SOURCE_ACCOUNT]:role/[ROLE_TO_ASSUME]"
                ]
            }
        ]
    }

**Note:** A period of 4 hours (469822 seconds) is hardcoded into the sts:assume call made in the RDS snapshot class, since snapshot creation can take a very long time. This must therefore be the minimum value for the role's `max-session-duration`.

The following policy is needed for usage of this subcommand, attach it to the role you'll be assuming:

    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "KMSEncrypt",
                "Effect": "Allow",
                "Action": [
                    "kms:GetPublicKey",
                    "kms:ImportKeyMaterial",
                    "kms:Decrypt",
                    "kms:UntagResource",
                    "kms:PutKeyPolicy",
                    "kms:GenerateDataKeyWithoutPlaintext",
                    "kms:Verify",
                    "kms:ListResourceTags",
                    "kms:GenerateDataKeyPair",
                    "kms:GetParametersForImport",
                    "kms:TagResource",
                    "kms:Encrypt",
                    "kms:GetKeyRotationStatus",
                    "kms:ReEncryptTo",
                    "kms:DescribeKey",
                    "kms:Sign",
                    "kms:CreateGrant",
                    "kms:ListKeyPolicies",
                    "kms:UpdateKeyDescription",
                    "kms:ListRetirableGrants",
                    "kms:GetKeyPolicy",
                    "kms:GenerateDataKeyPairWithoutPlaintext",
                    "kms:ReEncryptFrom",
                    "kms:RetireGrant",
                    "kms:ListGrants",
                    "kms:UpdateAlias",
                    "kms:RevokeGrant",
                    "kms:GenerateDataKey",
                    "kms:CreateAlias"
                ],
                "Resource": [
                    "arn:aws:kms:*:*:alias/*",
                    "arn:aws:kms:*:*:key/*"
                ]
            },
            {
                "Sid": "KMSCreate",
                "Effect": "Allow",
                "Action": [
                    "kms:DescribeCustomKeyStores",
                    "kms:ListKeys",
                    "kms:GenerateRandom",
                    "kms:UpdateCustomKeyStore",
                    "kms:ListAliases",
                    "kms:CreateKey",
                    "kms:ConnectCustomKeyStore",
                    "kms:CreateCustomKeyStore"
                ],
                "Resource": "*"
            }
        ]
    }

The following further policies need to be attached to the assume roles to backup each service:

#### RDS / RDS Aurora

    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "RDSBackup",
                "Effect": "Allow",
                "Action": [
                    "rds:DescribeDBClusterSnapshotAttributes",
                    "rds:AddTagsToResource",
                    "rds:RestoreDBClusterFromSnapshot",
                    "rds:DescribeDBSnapshots",
                    "rds:DescribeGlobalClusters",
                    "rds:CopyDBSnapshot",
                    "rds:CopyDBClusterSnapshot",
                    "rds:DescribeDBSnapshotAttributes",
                    "rds:ModifyDBSnapshot",
                    "rds:ListTagsForResource",
                    "rds:CreateDBSnapshot",
                    "rds:DescribeDBClusterSnapshots",
                    "rds:DescribeDBInstances",
                    "rds:CreateDBClusterSnapshot",
                    "rds:ModifyDBClusterSnapshotAttribute",
                    "rds:ModifyDBSnapshotAttribute",
                    "rds:DescribeDBClusters",
                    "rds:DeleteDBSnapshot",
                    "rds:DeleteDBClusterSnapshot"
                ],
                "Resource": "*"
            }
        ]
    }

#### S3

    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "S3RW",
                "Effect": "Allow",
                "Action": [
                    "s3:ListBucketMultipartUploads",
                    "s3:GetObjectRetention",
                    "s3:GetObjectVersionTagging",
                    "s3:ListBucketVersions",
                    "s3:CreateBucket",
                    "s3:ListBucket",
                    "s3:GetBucketVersioning",
                    "s3:GetBucketAcl",
                    "s3:GetObjectAcl",
                    "s3:GetObject",
                    "s3:GetEncryptionConfiguration",
                    "s3:ListAllMyBuckets",
                    "s3:PutLifecycleConfiguration",
                    "s3:GetObjectVersionAcl",
                    "s3:GetObjectTagging",
                    "s3:GetObjectVersionForReplication",
                    "s3:HeadBucket",
                    "s3:GetBucketLocation",
                    "s3:PutBucketVersioning",
                    "s3:GetObjectVersion",
                    "s3:PutObject",
                    "s3:PutObjectAcl",
                    "s3:PutEncryptionConfiguration",
                    "s3:PutBucketPolicy"
                ],
                "Resource": "*"
            }
        ]
    }

## Container

Limited functionality for interactive with EKS and ECR. At the moment it's just getting a docker login via an assumed role to another assumed role:

    akinaka container --region eu-west-1 --role-arn arn:aws:iam::0123456789:role/registry-rw get-ecr-login --registry 0123456789

The above will assume the role `arn:aws:iam::0123456789:role/registry-rw` in the account with the registry, and spit out a `docker login` line for you to use — exactly like `aws ecr get-login`, but working for assumed roles.

## Billing

Get a view of your daily AWS estimated bill for the x number of days. Defaults to today's estimated bill.

    akinaka reporting --region us-east-1 \
      --role-arn arn:aws:iam::1234567890:role/billing_assumerole \
      bill-estimates --from-days-ago 1

Example output:

    Today's estimated bill
    +------------+-----------+
    | Date       | Total     |
    |------------+-----------|
    | 2019-03-14 | USD 13.93 |
    +------------+-----------+

You can specify any integer value to the `--days-ago` flag. It's optional. Default value set for today (current day).

You can specify any region to the `--region` flag.

## Contributing

Modules can be added easily by simply dropping them in and adding an entry into `akinaka` to include them, and some `click` code in their `__init__` (or elsewhere that's loaded, but this is the cleanest way).

For example, given a module called `akinaka_moo`, and a single command and file called `moo`, add these two lines in the appropriate places of `akinaka`:

    from akinaka_update.commands import moo as moo_commands
    cli.add_command(moo_commands)

and the following in the module's `commands.py`:

    @click.group()
    @click.option("--make-awesome", help="The way in which to make moo awesome")
    def moo(make_awesome):
        import .moo
        # YOUR CODE USING THE MOO MODULE

Adding commands that need subcommands isn't too different, but you might want to take a look at the already present examples of `update` and `cleanup`.
