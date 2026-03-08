#!/usr/bin/env python3
"""
AgenticAIOps Diagnosis Runner

Runs multi-agent diagnosis on injected faults using ACI and Voting.
Based on AIOpsLab P=⟨T,C,S⟩ framework.

Flow:
1. Collect telemetry via ACI (logs, events, metrics)
2. Multi-agent analysis
3. Weighted voting for consensus
4. Report diagnosis result
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.aci import AgentCloudInterface
from src.voting import MultiAgentVoting, TaskType, AGENT_ROLES

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_NAMESPACE = "stress-test"


class DiagnosisRunner:
    """
    Runs automated diagnosis using ACI and Multi-Agent Voting.
    """
    
    def __init__(self, namespace: str = DEFAULT_NAMESPACE):
        self.namespace = namespace
        self.aci = AgentCloudInterface(
            cluster_name="testing-cluster",
            region="ap-southeast-1"
        )
        self.voting = MultiAgentVoting()
    
    def collect_telemetry(self) -> dict:
        """
        Collect telemetry data using ACI.
        
        Returns:
            Dict with logs, events, and metrics
        """
        logger.info(f"Collecting telemetry from namespace: {self.namespace}")
        
        telemetry = {
            "timestamp": datetime.now().isoformat(),
            "namespace": self.namespace,
        }
        
        # Get events (most useful for fault detection)
        events_result = self.aci.get_events(
            namespace=self.namespace,
            event_type="Warning",
            duration_minutes=10,
            limit=20
        )
        telemetry["events"] = events_result.to_dict()
        
        # Get logs
        logs_result = self.aci.get_logs(
            namespace=self.namespace,
            severity="error",
            duration_minutes=5,
            limit=50
        )
        telemetry["logs"] = logs_result.to_dict()
        
        # Get metrics (via kubectl top for simplicity)
        metrics_result = self.aci.get_metrics(
            namespace=self.namespace,
            metric_names=["cpu_usage", "memory_usage"]
        )
        telemetry["metrics"] = metrics_result.to_dict()
        
        return telemetry
    
    def analyze_fault(self, telemetry: dict) -> dict:
        """
        Analyze telemetry to detect fault type.
        
        Returns:
            Dict with detected fault and confidence
        """
        events = telemetry.get("events", {}).get("data", [])
        
        # Analyze events for fault patterns
        fault_indicators = {
            "oom": ["OOMKilled", "OOMKilling", "memory"],
            "imagepull": ["ImagePullBackOff", "ErrImagePull", "Failed to pull"],
            "crashloop": ["CrashLoopBackOff", "BackOff"],
            "cpu": ["throttl", "cpu"],
            "service": ["no endpoints", "endpoint"],
        }
        
        detected_faults = []
        
        for event in events:
            message = str(event.get("message", "")).lower()
            reason = str(event.get("reason", "")).lower()
            
            for fault_type, indicators in fault_indicators.items():
                for indicator in indicators:
                    if indicator.lower() in message or indicator.lower() in reason:
                        detected_faults.append({
                            "type": fault_type,
                            "evidence": event,
                            "confidence": 0.9
                        })
                        break
        
        return {
            "detected_faults": detected_faults,
            "total_events": len(events),
            "warning_count": len([e for e in events if e.get("event_type") == "Warning"])
        }
    
    def simulate_agent_analysis(self, telemetry: dict, fault_analysis: dict) -> dict:
        """
        Simulate multi-agent analysis (in real scenario, each agent would analyze independently).
        
        For now, we simulate different "perspectives" based on role expertise.
        """
        detected = fault_analysis.get("detected_faults", [])
        
        if not detected:
            return {
                "architect": "No clear fault pattern detected. Need more investigation.",
                "developer": "Logs look normal. Check application code.",
                "tester": "No test failures detected. System appears healthy.",
                "reviewer": "Insufficient evidence for diagnosis."
            }
        
        primary_fault = detected[0]["type"]
        evidence = detected[0].get("evidence", {})
        
        # Generate role-specific analysis
        responses = {}
        
        if primary_fault == "oom":
            responses = {
                "architect": f"OOMKilled detected. Root cause: Memory limit too low for workload. "
                            f"Recommend increasing memory limit. Evidence: {evidence.get('reason', 'OOMKilled')}",
                "developer": f"Container killed due to OOM. Memory exceeded limit. "
                            f"Fix: Optimize memory usage or increase limits.",
                "tester": f"Memory fault confirmed via events. OOMKilled pattern detected. "
                         f"This is a resource configuration issue.",
                "reviewer": f"Diagnosis: OOM (Out of Memory). High confidence based on K8s events. "
                           f"Recommended action: Increase memory limits."
            }
        elif primary_fault == "imagepull":
            responses = {
                "architect": f"ImagePullBackOff detected. Image configuration error. "
                            f"Check image name and registry access.",
                "developer": f"Container image pull failed. Verify image exists and credentials. "
                            f"Evidence: {evidence.get('message', 'Image pull failed')}",
                "tester": f"Image pull failure confirmed. This is a deployment configuration issue.",
                "reviewer": f"Diagnosis: ImagePullBackOff. Image not accessible. "
                           f"Fix image reference or registry credentials."
            }
        elif primary_fault == "cpu":
            responses = {
                "architect": f"CPU throttling detected. Resource contention issue. "
                            f"Consider increasing CPU limits.",
                "developer": f"High CPU usage causing throttling. Optimize code or increase limits.",
                "tester": f"CPU performance issue confirmed via metrics.",
                "reviewer": f"Diagnosis: CPU throttling. Workload exceeds allocated resources."
            }
        else:
            responses = {
                "architect": f"Fault detected: {primary_fault}. Investigating root cause.",
                "developer": f"Issue identified: {primary_fault}. Checking implementation.",
                "tester": f"Fault type: {primary_fault}. Running verification.",
                "reviewer": f"Analysis complete. Fault: {primary_fault}."
            }
        
        return responses
    
    def run_diagnosis(self) -> dict:
        """
        Run full diagnosis pipeline.
        
        Returns:
            Complete diagnosis report
        """
        start_time = time.time()
        
        logger.info("="*60)
        logger.info("Starting AgenticAIOps Diagnosis")
        logger.info("="*60)
        
        # Step 1: Collect telemetry
        logger.info("Step 1: Collecting telemetry via ACI...")
        telemetry = self.collect_telemetry()
        
        # Step 2: Analyze fault patterns
        logger.info("Step 2: Analyzing fault patterns...")
        fault_analysis = self.analyze_fault(telemetry)
        
        # Step 3: Multi-agent analysis
        logger.info("Step 3: Running multi-agent analysis...")
        agent_responses = self.simulate_agent_analysis(telemetry, fault_analysis)
        
        # Step 4: Weighted voting
        logger.info("Step 4: Executing weighted voting...")
        voting_result = self.voting.vote(
            task_type=TaskType.ANALYSIS,
            query="What is the root cause of the fault?",
            agent_responses=agent_responses,
            extract_fn=lambda x: x.split(".")[0].lower().split()[-1]  # Simple extraction
        )
        
        # Compile report
        diagnosis_time = time.time() - start_time
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "namespace": self.namespace,
            "diagnosis_time_seconds": round(diagnosis_time, 2),
            "telemetry_summary": {
                "events_collected": len(telemetry.get("events", {}).get("data", [])),
                "logs_collected": len(telemetry.get("logs", {}).get("data", [])),
            },
            "fault_analysis": fault_analysis,
            "agent_responses": agent_responses,
            "voting_result": voting_result.to_dict(),
            "final_diagnosis": voting_result.final_answer,
            "consensus": voting_result.consensus,
            "confidence": voting_result.agreement_ratio,
        }
        
        return report


def main():
    parser = argparse.ArgumentParser(description="Run AgenticAIOps diagnosis")
    parser.add_argument("--namespace", "-n", default=DEFAULT_NAMESPACE)
    parser.add_argument("--output", "-o", help="Output file for report (JSON)")
    
    args = parser.parse_args()
    
    runner = DiagnosisRunner(namespace=args.namespace)
    report = runner.run_diagnosis()
    
    # Print report
    print("\n" + "="*60)
    print("DIAGNOSIS REPORT")
    print("="*60)
    print(f"Namespace: {report['namespace']}")
    print(f"Time: {report['diagnosis_time_seconds']}s")
    print(f"\nFinal Diagnosis: {report['final_diagnosis']}")
    print(f"Consensus: {'Yes' if report['consensus'] else 'No'}")
    print(f"Confidence: {report['confidence']:.0%}")
    print("\nAgent Votes:")
    for agent, response in report['agent_responses'].items():
        print(f"  {agent}: {response[:60]}...")
    print("="*60 + "\n")
    
    # Save to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"Report saved to: {args.output}")


if __name__ == "__main__":
    main()
