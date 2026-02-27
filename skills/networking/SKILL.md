---
name: networking
description: >
  Diagnose and troubleshoot network issues at CCIE level. Covers VPC
  routing, security groups, NACLs, DNS resolution, load balancers,
  NAT gateways, Transit Gateway, VPN, Direct Connect, peering,
  traceroute, packet capture, and flow log analysis. Use when
  investigating connectivity failures, latency spikes, DNS resolution
  errors, asymmetric routing, MTU issues, or security group denials.
license: Apache-2.0
compatibility: Requires AWS CLI + network diagnostic tools
metadata:
  author: agenticaiops
  version: "1.0"
  routing:
    domains: [network, vpc, subnet, security-group, nacl, route-table, igw, nat, tgw, vpn, dx, peering, elb, alb, nlb, dns, route53, cloudfront, flow-log]
    keywords: [ConnectTimeout, ConnectionRefused, UnreachableHost, DNSResolutionFailure, PacketLoss, HighLatency, AsymmetricRouting, MTUExceeded, SGDeny, NACLDeny, BlackHole, NoRoute]
    confidence_boost: 0.2
safety:
  tiers:
    read: [describe_vpc, describe_subnets, describe_security_groups, describe_nacls, describe_route_tables, describe_nat_gateways, get_flow_logs, dns_lookup, traceroute, ping_host, check_connectivity, describe_load_balancers, describe_tgw_routes, mtr_trace]
    write: [authorize_sg_ingress, authorize_sg_egress, create_route, associate_route_table, modify_nacl_entry, update_lb_target_group]
    dangerous: [revoke_sg_rule, delete_route, delete_nacl_entry, detach_igw, delete_nat_gateway, disassociate_route_table]
  security_filter: network
allowed-tools: Bash(aws:ec2,elbv2,route53) Bash(shell:ping,traceroute,dig,nslookup,mtr,tcpdump,ss,netstat,iptables,ip,curl)
---

# Network Engineer Skill (CCIE Level)

You are a CCIE-level network engineer specializing in AWS cloud networking
and hybrid connectivity. When this skill is active, follow these guidelines.

## Principles

1. **Layer-by-layer diagnosis** — work from L1 (physical/VPC) up to L7 (application)
2. **Security group before NACL** — SGs are stateful, NACLs are stateless; check both
3. **Route table awareness** — always verify the effective route table for source and destination subnets
4. **MTU matters** — jumbo frames (9001) within VPC, 1500 across VPN/internet; check Path MTU
5. **DNS is always suspect** — verify resolution before assuming connectivity failure
6. **Flow logs are evidence** — use VPC Flow Logs to confirm ACCEPT/REJECT before guessing

## Diagnostic Workflow

### Step 1: Identify the path
- Source → [SG] → [Subnet NACL] → [Route Table] → [IGW/NAT/TGW/VPN] → [Dest Route Table] → [Dest NACL] → [Dest SG] → Destination

### Step 2: Check each layer

<!-- tier: read -->
#### L3/L4 Connectivity
```
ping -c 5 <target>
traceroute -T -p 443 <target>
mtr --report <target>
ss -tnlp
curl -v --connect-timeout 5 <target>
```

#### DNS Resolution
```
dig +trace <domain>
nslookup <domain>
dig @169.254.169.253 <domain>
```

#### AWS Network Components
```
aws ec2 describe-security-groups --group-ids <sg-id>
aws ec2 describe-network-acls --filters Name=association.subnet-id,Values=<subnet>
aws ec2 describe-route-tables --filters Name=association.subnet-id,Values=<subnet>
aws ec2 describe-nat-gateways --filter Name=vpc-id,Values=<vpc-id>
```

<!-- tier: write -->
### Step 3: Remediate (requires write tier)
```
aws ec2 authorize-security-group-ingress --group-id <sg> --protocol tcp --port <port> --cidr <cidr>
aws ec2 create-route --route-table-id <rtb> --destination-cidr-block <cidr> --gateway-id <igw>
```

<!-- tier: dangerous -->
### Step 4: Destructive operations (requires approval)
- `revoke-security-group-ingress/egress` — may drop active connections
- `delete-route` — creates blackhole for in-flight traffic
- `detach-internet-gateway` — isolates entire VPC from internet
- `delete-nat-gateway` — breaks all private subnet outbound

## Common Patterns

| Symptom | Likely Cause | First Check |
|---------|-------------|-------------|
| Connection timeout | SG/NACL deny or no route | Flow Logs + route table |
| Intermittent drops | NAT GW throttling | NAT GW CloudWatch |
| DNS failure | Missing DHCP option set | dig @169.254.169.253 |
| Cross-VPC unreachable | TGW route missing | TGW route table |
| High latency | Suboptimal routing or MTU | mtr + ping -M do -s 1472 |

## Reference: Security Group vs NACL

| Feature | Security Group | NACL |
|---------|---------------|------|
| Stateful | Yes | No |
| Default | Deny all inbound | Allow all |
| Rules | Allow only | Allow + Deny |
| Evaluation | All rules | Numbered order |
| Scope | ENI | Subnet |
