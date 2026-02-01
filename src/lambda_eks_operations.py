"""
AgenticAIOps - EKS Operations Lambda Function

This Lambda function handles Bedrock Agent action group invocations
for Kubernetes/EKS operations. It connects to EKS via kubectl.
"""

import json
import os
import subprocess
import tempfile
import boto3
from typing import Dict, Any


# Initialize clients
eks_client = boto3.client('eks', region_name=os.environ.get('AWS_REGION', 'ap-southeast-1'))
CLUSTER_NAME = os.environ.get('EKS_CLUSTER_NAME', 'aiops-demo')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle Bedrock Agent action invocations."""
    print(f"Event: {json.dumps(event)}")
    
    api_path = event.get('apiPath', '')
    http_method = event.get('httpMethod', 'GET')
    parameters = {p['name']: p['value'] for p in event.get('parameters', [])}
    request_body = parse_request_body(event.get('requestBody', {}))
    
    # Setup kubeconfig for EKS
    setup_kubeconfig()
    
    try:
        # Route to handler
        if api_path == '/pods' and http_method == 'GET':
            result = get_pods(parameters)
        elif '/pods/' in api_path and api_path.endswith('/logs'):
            pod_name = api_path.split('/')[2]
            result = get_pod_logs(pod_name, parameters)
        elif api_path.startswith('/pods/') and http_method == 'GET':
            pod_name = api_path.split('/')[2]
            result = describe_pod(pod_name, parameters)
        elif api_path == '/events':
            result = get_events(parameters)
        elif api_path == '/deployments' and http_method == 'GET':
            result = get_deployments(parameters)
        elif api_path.endswith('/scale'):
            name = api_path.split('/')[2]
            result = scale_deployment(name, parameters, request_body)
        elif api_path.endswith('/restart'):
            name = api_path.split('/')[2]
            result = restart_deployment(name, parameters)
        elif api_path.endswith('/rollback'):
            name = api_path.split('/')[2]
            result = rollback_deployment(name, parameters)
        elif api_path == '/nodes':
            result = get_nodes()
        elif api_path == '/cluster/health':
            result = get_cluster_health()
        elif api_path.startswith('/analyze/pod/'):
            pod_name = api_path.split('/')[3]
            result = analyze_pod(pod_name, parameters)
        else:
            result = {'success': False, 'error': f'Unknown path: {api_path}'}
        
        return format_response(api_path, http_method, result)
        
    except Exception as e:
        return format_response(api_path, http_method, {'success': False, 'error': str(e)}, 500)


def setup_kubeconfig():
    """Configure kubectl to use EKS cluster."""
    # Write kubeconfig using aws eks get-token
    kubeconfig = f"""
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: {get_cluster_ca()}
    server: {get_cluster_endpoint()}
  name: {CLUSTER_NAME}
contexts:
- context:
    cluster: {CLUSTER_NAME}
    user: aws
  name: {CLUSTER_NAME}
current-context: {CLUSTER_NAME}
kind: Config
users:
- name: aws
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1beta1
      command: aws
      args:
        - eks
        - get-token
        - --cluster-name
        - {CLUSTER_NAME}
"""
    kubeconfig_path = '/tmp/kubeconfig'
    with open(kubeconfig_path, 'w') as f:
        f.write(kubeconfig)
    os.environ['KUBECONFIG'] = kubeconfig_path


def get_cluster_endpoint():
    """Get EKS cluster endpoint."""
    response = eks_client.describe_cluster(name=CLUSTER_NAME)
    return response['cluster']['endpoint']


def get_cluster_ca():
    """Get EKS cluster CA certificate."""
    response = eks_client.describe_cluster(name=CLUSTER_NAME)
    return response['cluster']['certificateAuthority']['data']


def run_kubectl(args: list) -> Dict[str, Any]:
    """Run kubectl command and return output."""
    cmd = ['kubectl'] + args + ['-o', 'json']
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        return {'success': False, 'error': result.stderr}
    
    try:
        return {'success': True, 'data': json.loads(result.stdout)}
    except json.JSONDecodeError:
        return {'success': True, 'data': result.stdout}


def get_pods(params: Dict) -> Dict:
    """Get pods in namespace."""
    namespace = params.get('namespace', 'default')
    args = ['get', 'pods']
    
    if namespace != 'all':
        args.extend(['-n', namespace])
    else:
        args.append('--all-namespaces')
    
    if params.get('labelSelector'):
        args.extend(['-l', params['labelSelector']])
    
    result = run_kubectl(args)
    
    if result.get('success') and 'items' in result.get('data', {}):
        pods = []
        for item in result['data']['items']:
            pod_info = {
                'name': item['metadata']['name'],
                'namespace': item['metadata']['namespace'],
                'phase': item['status'].get('phase', 'Unknown'),
                'containers': []
            }
            
            for cs in item['status'].get('containerStatuses', []):
                container = {
                    'name': cs['name'],
                    'ready': cs['ready'],
                    'restartCount': cs['restartCount'],
                    'state': list(cs['state'].keys())[0] if cs.get('state') else 'unknown'
                }
                
                # Get state details
                if 'waiting' in cs.get('state', {}):
                    container['reason'] = cs['state']['waiting'].get('reason', '')
                elif 'terminated' in cs.get('state', {}):
                    container['reason'] = cs['state']['terminated'].get('reason', '')
                    container['exitCode'] = cs['state']['terminated'].get('exitCode', 0)
                
                pod_info['containers'].append(container)
            
            pods.append(pod_info)
        
        return {'success': True, 'count': len(pods), 'pods': pods}
    
    return result


def get_pod_logs(pod_name: str, params: Dict) -> Dict:
    """Get logs from a pod."""
    namespace = params.get('namespace', 'default')
    tail_lines = params.get('tailLines', '100')
    
    args = ['logs', pod_name, '-n', namespace, '--tail', str(tail_lines)]
    
    if params.get('container'):
        args.extend(['-c', params['container']])
    
    if params.get('previous') == 'true':
        args.append('--previous')
    
    # Don't use -o json for logs
    cmd = ['kubectl'] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        return {'success': False, 'error': result.stderr}
    
    return {'success': True, 'pod': pod_name, 'namespace': namespace, 'logs': result.stdout}


def describe_pod(pod_name: str, params: Dict) -> Dict:
    """Get detailed pod info."""
    namespace = params.get('namespace', 'default')
    return run_kubectl(['get', 'pod', pod_name, '-n', namespace])


def get_events(params: Dict) -> Dict:
    """Get cluster events."""
    namespace = params.get('namespace', 'default')
    args = ['get', 'events', '--sort-by=.lastTimestamp']
    
    if namespace != 'all':
        args.extend(['-n', namespace])
    else:
        args.append('--all-namespaces')
    
    if params.get('fieldSelector'):
        args.extend(['--field-selector', params['fieldSelector']])
    
    result = run_kubectl(args)
    
    if result.get('success') and 'items' in result.get('data', {}):
        events = []
        for item in result['data']['items'][:int(params.get('limit', 50))]:
            events.append({
                'type': item.get('type', 'Normal'),
                'reason': item.get('reason', ''),
                'message': item.get('message', ''),
                'object': f"{item['involvedObject'].get('kind', '')}/{item['involvedObject'].get('name', '')}",
                'count': item.get('count', 1),
                'lastTimestamp': item.get('lastTimestamp', '')
            })
        return {'success': True, 'count': len(events), 'events': events}
    
    return result


def get_deployments(params: Dict) -> Dict:
    """Get deployments."""
    namespace = params.get('namespace', 'default')
    args = ['get', 'deployments']
    
    if namespace != 'all':
        args.extend(['-n', namespace])
    else:
        args.append('--all-namespaces')
    
    result = run_kubectl(args)
    
    if result.get('success') and 'items' in result.get('data', {}):
        deployments = []
        for item in result['data']['items']:
            deployments.append({
                'name': item['metadata']['name'],
                'namespace': item['metadata']['namespace'],
                'replicas': {
                    'desired': item['spec'].get('replicas', 0),
                    'ready': item['status'].get('readyReplicas', 0),
                    'available': item['status'].get('availableReplicas', 0)
                }
            })
        return {'success': True, 'count': len(deployments), 'deployments': deployments}
    
    return result


def scale_deployment(name: str, params: Dict, body: Dict) -> Dict:
    """Scale a deployment."""
    namespace = params.get('namespace', 'default')
    replicas = body.get('replicas', 1)
    
    cmd = ['kubectl', 'scale', 'deployment', name, '-n', namespace, f'--replicas={replicas}']
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        return {'success': False, 'error': result.stderr}
    
    return {
        'success': True,
        'deployment': name,
        'namespace': namespace,
        'newReplicas': replicas,
        'message': f'Scaled {name} to {replicas} replicas'
    }


def restart_deployment(name: str, params: Dict) -> Dict:
    """Rolling restart a deployment."""
    namespace = params.get('namespace', 'default')
    
    cmd = ['kubectl', 'rollout', 'restart', 'deployment', name, '-n', namespace]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        return {'success': False, 'error': result.stderr}
    
    return {
        'success': True,
        'deployment': name,
        'namespace': namespace,
        'message': f'Rolling restart initiated for {name}'
    }


def rollback_deployment(name: str, params: Dict) -> Dict:
    """Rollback a deployment."""
    namespace = params.get('namespace', 'default')
    
    cmd = ['kubectl', 'rollout', 'undo', 'deployment', name, '-n', namespace]
    
    if params.get('revision'):
        cmd.extend([f'--to-revision={params["revision"]}'])
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        return {'success': False, 'error': result.stderr}
    
    return {
        'success': True,
        'deployment': name,
        'namespace': namespace,
        'message': f'Rollback initiated for {name}'
    }


def get_nodes() -> Dict:
    """Get node status."""
    result = run_kubectl(['get', 'nodes'])
    
    if result.get('success') and 'items' in result.get('data', {}):
        nodes = []
        for item in result['data']['items']:
            conditions = {c['type']: c['status'] for c in item['status'].get('conditions', [])}
            nodes.append({
                'name': item['metadata']['name'],
                'status': 'Ready' if conditions.get('Ready') == 'True' else 'NotReady',
                'instanceType': item['metadata'].get('labels', {}).get('node.kubernetes.io/instance-type', 'unknown'),
                'conditions': conditions
            })
        return {'success': True, 'count': len(nodes), 'nodes': nodes}
    
    return result


def get_cluster_health() -> Dict:
    """Comprehensive cluster health check."""
    health = {'overall': 'healthy', 'checks': {}}
    
    # Check nodes
    nodes_result = get_nodes()
    if nodes_result.get('success'):
        unhealthy = [n for n in nodes_result['nodes'] if n['status'] != 'Ready']
        health['checks']['nodes'] = {
            'total': len(nodes_result['nodes']),
            'unhealthy': len(unhealthy),
            'status': 'healthy' if not unhealthy else 'degraded'
        }
        if unhealthy:
            health['overall'] = 'degraded'
    
    # Check pods
    pods_result = get_pods({'namespace': 'all'})
    if pods_result.get('success'):
        problem_pods = [p for p in pods_result['pods'] if p['phase'] not in ['Running', 'Succeeded']]
        health['checks']['pods'] = {
            'total': len(pods_result['pods']),
            'problems': len(problem_pods),
            'status': 'healthy' if not problem_pods else 'warning'
        }
        if problem_pods:
            health['overall'] = 'warning' if health['overall'] == 'healthy' else health['overall']
    
    return {'success': True, 'health': health}


def analyze_pod(pod_name: str, params: Dict) -> Dict:
    """Analyze pod issues."""
    namespace = params.get('namespace', 'default')
    
    findings = []
    recommendations = []
    severity = 'info'
    
    # Get pod status
    pod_result = run_kubectl(['get', 'pod', pod_name, '-n', namespace])
    if not pod_result.get('success'):
        return {'success': False, 'error': f'Pod not found: {pod_name}'}
    
    pod = pod_result['data']
    phase = pod['status'].get('phase', 'Unknown')
    
    # Analyze container statuses
    for cs in pod['status'].get('containerStatuses', []):
        restart_count = cs.get('restartCount', 0)
        
        if restart_count > 5:
            findings.append(f"Container {cs['name']} has restarted {restart_count} times")
            severity = 'warning'
        
        state = cs.get('state', {})
        if 'waiting' in state:
            reason = state['waiting'].get('reason', '')
            if reason == 'CrashLoopBackOff':
                findings.append(f"Container {cs['name']} is in CrashLoopBackOff")
                recommendations.append("Check container logs for error messages")
                severity = 'critical'
            elif reason == 'ImagePullBackOff':
                findings.append(f"Container {cs['name']} cannot pull image")
                recommendations.append("Verify image name and registry credentials")
                severity = 'critical'
        
        if 'terminated' in state:
            reason = state['terminated'].get('reason', '')
            if reason == 'OOMKilled':
                findings.append(f"Container {cs['name']} was OOMKilled")
                recommendations.append("Increase memory limits")
                severity = 'critical'
    
    # Get logs for more context
    logs_result = get_pod_logs(pod_name, {'namespace': namespace, 'tailLines': '50'})
    if logs_result.get('success'):
        logs = logs_result.get('logs', '')
        if 'ERROR' in logs or 'FATAL' in logs:
            findings.append("Error messages found in logs")
            recommendations.append("Review logs for root cause")
    
    return {
        'success': True,
        'pod': pod_name,
        'namespace': namespace,
        'phase': phase,
        'severity': severity,
        'findings': findings,
        'recommendations': recommendations
    }


def parse_request_body(body: Dict) -> Dict:
    """Parse request body from Bedrock Agent format."""
    if not body:
        return {}
    
    content = body.get('content', {})
    json_content = content.get('application/json', {})
    
    if 'properties' in json_content:
        return json_content['properties']
    
    return json_content


def format_response(api_path: str, http_method: str, result: Dict, status_code: int = 200) -> Dict:
    """Format response for Bedrock Agent."""
    return {
        'messageVersion': '1.0',
        'response': {
            'actionGroup': 'eks-operations',
            'apiPath': api_path,
            'httpMethod': http_method,
            'httpStatusCode': status_code,
            'responseBody': {
                'application/json': {
                    'body': json.dumps(result)
                }
            }
        }
    }
