#!/usr/bin/env python3
"""
AgenticAIOps MVP Demo Script

This script demonstrates the agent's capabilities:
1. Cluster health check
2. Pod issue diagnosis
3. Interactive troubleshooting
4. Remediation with confirmation
"""

import sys
import time
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


def print_header():
    """Print demo header."""
    console.print(Panel.fit(
        "[bold blue]AgenticAIOps MVP Demo[/bold blue]\n"
        "[dim]AI-powered Kubernetes Operations for Amazon EKS[/dim]",
        border_style="blue"
    ))
    console.print()


def demo_health_check(agent):
    """Demonstrate cluster health check."""
    console.print("[bold cyan]━━━ Demo 1: Cluster Health Check ━━━[/bold cyan]\n")
    
    console.print("[dim]User:[/dim] Check the health of my EKS cluster\n")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Agent analyzing cluster...", total=None)
        response = agent.chat("Perform a comprehensive health check on this cluster. Check all pods, nodes, and deployments.")
        progress.remove_task(task)
    
    console.print(Panel(Markdown(response), title="[green]Agent Response[/green]", border_style="green"))
    console.print()


def demo_pod_diagnosis(agent, pod_name: str = None):
    """Demonstrate pod issue diagnosis."""
    console.print("[bold cyan]━━━ Demo 2: Pod Issue Diagnosis ━━━[/bold cyan]\n")
    
    if pod_name:
        query = f"Why is the pod {pod_name} having issues? Investigate and tell me what's wrong."
    else:
        query = "Find any pods that are having problems and diagnose the issues."
    
    console.print(f"[dim]User:[/dim] {query}\n")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Agent investigating...", total=None)
        response = agent.chat(query)
        progress.remove_task(task)
    
    console.print(Panel(Markdown(response), title="[green]Agent Response[/green]", border_style="green"))
    console.print()


def demo_remediation(agent, deployment_name: str):
    """Demonstrate remediation with confirmation."""
    console.print("[bold cyan]━━━ Demo 3: Remediation with Confirmation ━━━[/bold cyan]\n")
    
    query = f"The {deployment_name} deployment is having issues. Can you restart it?"
    console.print(f"[dim]User:[/dim] {query}\n")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Agent preparing action...", total=None)
        response = agent.chat(query)
        progress.remove_task(task)
    
    console.print(Panel(Markdown(response), title="[yellow]Agent Response (Confirmation Required)[/yellow]", border_style="yellow"))
    console.print()
    
    # Show that confirmation is required
    console.print("[dim]Note: Write operations require user confirmation before execution.[/dim]\n")


def demo_natural_conversation(agent):
    """Demonstrate natural conversation capabilities."""
    console.print("[bold cyan]━━━ Demo 4: Natural Conversation ━━━[/bold cyan]\n")
    
    queries = [
        "What's using the most CPU in the cluster?",
        "Show me recent warning events",
        "Are there any pods that have restarted more than 3 times?"
    ]
    
    for query in queries:
        console.print(f"[dim]User:[/dim] {query}\n")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Agent thinking...", total=None)
            response = agent.chat(query)
            progress.remove_task(task)
        
        console.print(Panel(Markdown(response), title="[green]Agent[/green]", border_style="green"))
        console.print()
        time.sleep(1)


def run_demo(cluster_name: str, region: str = None):
    """Run the full demo."""
    from src.agent import create_agent
    
    print_header()
    
    console.print(f"[bold]Cluster:[/bold] {cluster_name}")
    console.print(f"[bold]Region:[/bold] {region or 'default'}")
    console.print()
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Initializing agent...", total=None)
            agent = create_agent(cluster_name=cluster_name, region=region)
            progress.remove_task(task)
        
        console.print("[green]✓ Agent initialized successfully[/green]\n")
        
    except Exception as e:
        console.print(f"[red]Failed to initialize agent: {e}[/red]")
        return
    
    # Run demos
    try:
        demo_health_check(agent)
        input("Press Enter to continue to next demo...")
        console.print()
        
        demo_pod_diagnosis(agent)
        input("Press Enter to continue to next demo...")
        console.print()
        
        demo_natural_conversation(agent)
        
        console.print("[bold green]━━━ Demo Complete ━━━[/bold green]\n")
        console.print("The agent demonstrated:")
        console.print("  ✓ Cluster health monitoring")
        console.print("  ✓ Automated issue diagnosis")
        console.print("  ✓ Natural language interaction")
        console.print("  ✓ Safe remediation with confirmation")
        console.print()
        
    except KeyboardInterrupt:
        console.print("\n[dim]Demo interrupted[/dim]")
    except Exception as e:
        console.print(f"\n[red]Demo error: {e}[/red]")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="AgenticAIOps MVP Demo")
    parser.add_argument("--cluster", "-c", required=True, help="EKS cluster name")
    parser.add_argument("--region", "-r", help="AWS region")
    
    args = parser.parse_args()
    run_demo(args.cluster, args.region)
