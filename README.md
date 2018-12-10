# ecs-scale-cluster
Lambda to scale AWS ECS cluster automatically when needed. 

Language: Python 2.7

Parameters: 

ENV = {stg, live} -> string stg us-west-1 region, live us-east-1 region
CLUSTER_NAME = string with the name of the ECS cluster
ASG_NAME = string with the name of the ASG related to the cluster
INSTANCE_TYPE = string with the instance type of the ASG instances, example "c4.4xlarge"
MIN_COUNT = string with the minimum number of times the largest task fits in the cluster before a scale up event is called
MAX_COUNT = string with the minimum number of times the largest task fits in the cluster before a scale down event is called

Runs every time Cloudwatch receives an event related to ECS (from cluster instances or services tasks). Then it calculates the largest task (RAM and CPU) that is running on the cluster. Then it calculates (based on MIN_COUNT and MAX_COUNT) if the cluster needs more or less instances.   