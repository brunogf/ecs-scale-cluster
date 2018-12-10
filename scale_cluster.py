#!/usr/bin/python
import json
import boto3
import os

ecs = boto3.client('ecs')
asg = boto3.client('autoscaling')
cw = boto3.client('cloudwatch')

def find_largest_task(cluster):

    tasks = ecs.list_tasks(cluster=cluster)['taskArns']
    task_descs = ecs.describe_tasks(cluster=cluster, tasks=tasks)

    task_def_descs = []

    for task in task_descs["tasks"]:
        task_def_descs.append(ecs.describe_task_definition(taskDefinition=task["taskDefinitionArn"])["taskDefinition"])

    cpus = []
    rams = []

    for task in task_def_descs:
        cpu_cont = 0
        ram_cont = 0
        
        # In case task has several containers
        for container in task["containerDefinitions"]:
            cpu_cont += container["cpu"]
            ram_cont += container["memory"]
        
        cpus.append(cpu_cont)
        rams.append(ram_cont)

    # find task with largest cpu
    largest_cpu = 0
    for cpu in cpus:
        if cpu > largest_cpu:
            largest_cpu = cpu
        
    # find task with largest ram
    largest_ram = 0
    for ram in rams:
        if ram > largest_ram:
            largest_ram = ram

    return largest_cpu, largest_ram

def fits(cluster, cpu, ram):
    
    instances = ecs.list_container_instances(cluster=cluster, status='ACTIVE')
    instances_desc = ecs.describe_container_instances(cluster=cluster, containerInstances=instances["containerInstanceArns"])

    # how many times does largest cpu/ram fits into all instances
    fits = 0

    for instance in instances_desc["containerInstances"]:

        instance_remaining_cpu = instance["remainingResources"][0]["integerValue"]
        instance_remaining_ram = instance["remainingResources"][1]["integerValue"]

        while instance_remaining_cpu > 0:
            if instance_remaining_cpu >= cpu:
                if instance_remaining_ram >= ram:
                    instance_remaining_cpu -= cpu
                    instance_remaining_ram -= ram
                    fits += 1
                else:
                    break
            else:
                break
    
    return fits

# def fits_per_instance(cluster, cpu, ram):
#     instance_type = os.environ['INSTANCE_TYPE']
#     active_instances = ecs.list_container_instances(cluster=cluster, status='ACTIVE', filter='attribute:ecs.instance-type == ' + instance_type)["containerInstanceArns"]

#     if len(active_instances) > 0:
#         instance = ecs.describe_container_instances(cluster=cluster, containerInstances=[active_instances[0]])
#         instance_cpu = instance['containerInstances'][0]['registeredResources'][0]['integerValue']
#         instance_ram = instance['containerInstances'][0]['registeredResources'][1]['integerValue']

#     fpi = min(instance_ram/ram, instance_cpu/cpu)

#     if (fpi == 1):
#         min_fits = 3
#     else: 
#         min_fits = fpi

#     return min_fits, min_fits*2

def remove_draining(cluster):
    draining_instances = ecs.list_container_instances(cluster=cluster, status='DRAINING')["containerInstanceArns"]

    for instance in draining_instances:
        instance_id = ecs.describe_container_instances(cluster=cluster, containerInstances=[instance])["containerInstances"][0]["ec2InstanceId"]
        running_tasks = len(ecs.list_tasks(cluster=cluster, containerInstance=instance, desiredStatus='RUNNING')['taskArns'])
        if running_tasks == 0:
            print instance_id
            asg.terminate_instance_in_auto_scaling_group(InstanceId=instance_id, ShouldDecrementDesiredCapacity=True)

def instance_candidate(cluster):
    instance_type = os.environ['INSTANCE_TYPE']
    active_instances = ecs.list_container_instances(cluster=cluster, status='ACTIVE', filter='attribute:ecs.instance-type == ' + instance_type)["containerInstanceArns"]
    # filter cluster by instance type
    min_tasks = 100

    for instance in active_instances: 
        running_tasks = len(ecs.list_tasks(cluster=cluster, containerInstance=instance, desiredStatus='RUNNING'))
        if (running_tasks < min_tasks):
            min_tasks = running_tasks
            candidate = instance

    return candidate, min_tasks


def lambda_handler(event, context):
    # print('Event:')
    # print(json.dumps(event))

    if event["source"] != "aws.ecs":
       raise ValueError("Function only supports input from events with a source type of: aws.ecs")

    cluster = os.environ['CLUSTER_NAME']
    asg_name = os.environ['ASG_NAME']
    instance_type = os.environ['INSTANCE_TYPE'] # ASG related to the cluster LC instance type
    min_count = int(os.environ['MIN_COUNT']) # Min number of largest tasks that must fit, if less scale up
    max_count = int(os.environ['MAX_COUNT']) # Max number of largest tasks that fit, if more scale down

    # Remove draining instances with no tasks running
    print ('Removing draining instances...')
    remove_draining(cluster)

    print('Calculating scaling needs for ' + cluster + '...')

    largest_cpu, largest_ram = find_largest_task(cluster)
    print 'Largest CPU: ' + str(largest_cpu)
    print 'Largest RAM: ' + str(largest_ram)
    
    count = fits(cluster, largest_cpu, largest_ram)
    print 'Largest task fits ' + str(count) + ' times in the cluster' # Task with largest CPU and task (maybe not the same) with largest RAM

    asg_desc = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    asg_capacity = asg_desc["AutoScalingGroups"][0]["DesiredCapacity"]

    if (count < min_count):
        asg.set_desired_capacity(AutoScalingGroupName=asg_name, DesiredCapacity=asg_capacity+1, HonorCooldown=True)
        print 'Scaling up from ' + str(asg_capacity) + ' to ' + str(asg_capacity+1)
    elif (count > max_count):
        draining_instances = ecs.list_container_instances(cluster=cluster, status='DRAINING')["containerInstanceArns"]
        if (len(draining_instances)==0):
            instance, min_tasks = instance_candidate(cluster)
            instance_id = ecs.describe_container_instances(cluster=cluster, containerInstances=[instance])["containerInstances"][0]["ec2InstanceId"]
            ecs.update_container_instances_state(cluster=cluster, containerInstances=[instance], status='DRAINING')
            print 'Scaling down, draining instance ' + instance_id + ' with ' + str(min_tasks) + ' running tasks'
        else:
            print 'Instances still draining, do nothing'
    else:
        print 'Stable'
