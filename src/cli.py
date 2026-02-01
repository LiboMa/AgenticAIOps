"""
AgenticAIOps - CLI Interface

Command-line interface for interacting with the agent.
"""

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from .agent import create_agent


console = Console()


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """AgenticAIOps - AI-powered Kubernetes operations for EKS."""
    pass


@cli.command()
@click.option("--cluster", "-c", required=True, help="EKS cluster name")
@click.option("--region", "-r", help="AWS region")
@click.option("--model", "-m", default="claude-sonnet-4-20250514", help="Claude model to use")
@click.option("--no-confirm", is_flag=True, help="Disable confirmation for write operations")
def chat(cluster: str, region: str, model: str, no_confirm: bool):
    """Start an interactive chat session with the agent."""
    
    console.print(Panel.fit(
        "[bold blue]AgenticAIOps[/bold blue] - AI-powered EKS Operations\n"
        f"Cluster: [green]{cluster}[/green]\n"
        f"Model: [cyan]{model}[/cyan]\n"
        "Type 'exit' or 'quit' to end the session.",
        title="Welcome"
    ))
    
    try:
        agent = create_agent(
            cluster_name=cluster,
            region=region,
            model=model,
            require_confirmation=not no_confirm
        )
    except Exception as e:
        console.print(f"[red]Failed to initialize agent: {e}[/red]")
        return
    
    console.print("\n[dim]Agent initialized successfully. How can I help?[/dim]\n")
    
    while True:
        try:
            user_input = Prompt.ask("[bold cyan]You[/bold cyan]")
            
            if user_input.lower().strip() in ["exit", "quit", "q"]:
                console.print("[dim]Goodbye![/dim]")
                break
            
            if not user_input.strip():
                continue
            
            with console.status("[bold green]Thinking...[/bold green]"):
                response = agent.chat(user_input)
            
            console.print()
            console.print(Panel(
                Markdown(response),
                title="[bold green]Agent[/bold green]",
                border_style="green"
            ))
            console.print()
            
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted. Type 'exit' to quit.[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.option("--cluster", "-c", required=True, help="EKS cluster name")
@click.option("--region", "-r", help="AWS region")
@click.argument("query")
def ask(cluster: str, region: str, query: str):
    """Ask a single question and get a response."""
    
    try:
        agent = create_agent(
            cluster_name=cluster,
            region=region,
            require_confirmation=False  # Non-interactive mode
        )
        
        response = agent.chat(query)
        console.print(Markdown(response))
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


@cli.command()
@click.option("--cluster", "-c", required=True, help="EKS cluster name")
@click.option("--region", "-r", help="AWS region")
def health(cluster: str, region: str):
    """Quick cluster health check."""
    
    try:
        agent = create_agent(cluster_name=cluster, region=region)
        
        with console.status("[bold green]Checking cluster health...[/bold green]"):
            response = agent.chat(f"Perform a health check on cluster {cluster}")
        
        console.print(Markdown(response))
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


@cli.command()
@click.option("--cluster", "-c", required=True, help="EKS cluster name")
@click.option("--region", "-r", help="AWS region")
@click.option("--namespace", "-n", default="default", help="Kubernetes namespace")
def pods(cluster: str, region: str, namespace: str):
    """List pods and their status."""
    
    try:
        agent = create_agent(cluster_name=cluster, region=region)
        
        with console.status("[bold green]Fetching pods...[/bold green]"):
            response = agent.chat(f"List all pods in namespace {namespace} and show their status")
        
        console.print(Markdown(response))
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


def main():
    """Entry point."""
    cli()


if __name__ == "__main__":
    main()
