#!/usr/bin/env python3
"""
CLI utility to manage users in the LLMaven proxy authentication system.

see python infra/users.py --help for usage.
"""

import os
import secrets
import uuid
from datetime import datetime
from typing import Optional

import typer
from azure.data.tables import TableServiceClient
from azure.core.credentials import AzureNamedKeyCredential
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError, HttpResponseError
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="users",
    help="Manage users for the LLMaven proxy authentication system",
    add_completion=False,
)
console = Console()

TABLE_NAME = "userkeys"


def get_table_client():
    """Get Azure Table Storage client."""
    load_dotenv()
    
    account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
    
    if not account_name or not account_key:
        console.print(
            "[red]✗ Error:[/red] AZURE_STORAGE_ACCOUNT_NAME and AZURE_STORAGE_ACCOUNT_KEY "
            "must be set in environment or .env file",
            style="red"
        )
        console.print("\n[yellow]See infra/README.md for setup instructions[/yellow]")
        raise typer.Exit(1)
    
    account_url = f"https://{account_name}.table.core.windows.net"
    credential = AzureNamedKeyCredential(account_name, account_key)
   
    table_service = TableServiceClient(
        endpoint=account_url,
        credential=credential
    )
   
    return table_service.get_table_client(TABLE_NAME)


@app.command()
def add(
    user_name: str = typer.Argument(..., help="User's full name"),
    user_id: Optional[str] = typer.Option(None, "--user-id", "-u", help="Custom user ID (default: auto-generated GUID)")
):
    """
    Add a new user to the authentication system.
    
    Generates a unique user ID and API key, then inserts into Azure Table Storage.
    """
    try:
        table_client = get_table_client()
        
        # Generate credentials
        if not user_id:
            user_id = str(uuid.uuid4())
        api_key = secrets.token_hex(32)
        created_at = datetime.utcnow().isoformat() + "Z"
        
        # Create entity
        entity = {
            "PartitionKey": "user",
            "RowKey": user_id,
            "api_key": api_key,
            "user_name": user_name,
            "created_at": created_at,
        }
        
        # Insert into table
        console.print(f"\n[yellow]Adding user '{user_name}'...[/yellow]")
        
        try:
            table_client.create_entity(entity=entity)
        except ResourceExistsError:
            console.print(f"[red]✗ Error:[/red] User with ID {user_id} already exists", style="red")
            raise typer.Exit(1)
        except HttpResponseError as e:
            if "TableNotFound" in str(e):
                console.print(
                    f"\n[red]✗ Error:[/red] Table '{TABLE_NAME}' not found",
                    style="red"
                )
                console.print("\n[yellow]To create the table, run:[/yellow]")
                console.print("  pixi run setup-proxy")
            else:
                console.print(f"[red]✗ Azure Table Storage error:[/red] {e}", style="red")
            raise typer.Exit(1)
        
        # Display results
        console.print("\n[green]" + "=" * 70 + "[/green]")
        console.print("[green bold]USER CREATED SUCCESSFULLY[/green bold]")
        console.print("[green]" + "=" * 70 + "[/green]")
        console.print(f"[cyan]User Name:[/cyan]  {user_name}")
        console.print(f"[cyan]User ID:[/cyan]    {user_id}")
        console.print(f"[cyan]Created:[/cyan]    {created_at}")
        console.print("\n[yellow]" + "-" * 70 + "[/yellow]")
        console.print("[yellow bold]API KEY (save this - it won't be shown again):[/yellow bold]")
        console.print("[yellow]" + "-" * 70 + "[/yellow]")
        console.print(f"[green bold]{api_key}[/green bold]")
        console.print("[yellow]" + "-" * 70 + "[/yellow]")
        
        console.print("\n[cyan]The user can now authenticate using:[/cyan]")
        console.print(f"  Authorization: Bearer {api_key}")
        
        console.print("\n[cyan]Example curl command:[/cyan]")
        console.print(f"""  curl http://localhost:8000/v1/models \\
    -H "Authorization: Bearer {api_key}\"""")
        console.print()
        
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[red]✗ Unexpected error:[/red] {e}", style="red")
        raise typer.Exit(1)


@app.command(name="list")
def list_users(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full details including API keys"),
):
    """
    List all users in the authentication system.
    """
    try:
        table_client = get_table_client()
        
        # Query all users
        try:
            entities = table_client.query_entities("PartitionKey eq 'user'")
            users = list(entities)
        except HttpResponseError as e:
            if "TableNotFound" in str(e):
                console.print(f"[red]✗ Error:[/red] Table '{TABLE_NAME}' not found", style="red")
                console.print("\n[yellow]Run 'pixi run setup-proxy' first[/yellow]")
            else:
                console.print(f"[red]✗ Azure Table Storage error:[/red] {e}", style="red")
            raise typer.Exit(1)
        
        if not users:
            console.print("\n[yellow]No users found[/yellow]\n")
            return
        
        # Create table
        table = Table(title=f"\nUsers in {TABLE_NAME}", show_lines=True)
        table.add_column("User Name", style="cyan")
        table.add_column("User ID", style="green")
        table.add_column("Created", style="yellow")
        if verbose:
            table.add_column("API Key", style="magenta")
        
        # Add rows
        for user in users:
            row = [
                user.get("user_name", "N/A"),
                user.get("RowKey", "N/A"),
                user.get("created_at", "N/A"),
            ]
            if verbose:
                row.append(user.get("api_key", "N/A"))
            table.add_row(*row)
        
        console.print(table)
        console.print(f"\n[cyan]Total users:[/cyan] {len(users)}\n")
        
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[red]✗ Unexpected error:[/red] {e}", style="red")
        raise typer.Exit(1)


@app.command()
def delete(
    user_id: str = typer.Argument(..., help="User ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a user from the authentication system.
    """
    try:
        table_client = get_table_client()
        
        # Get user first to show info
        try:
            user = table_client.get_entity("user", user_id)
            user_name = user.get("user_name", "Unknown")
        except ResourceNotFoundError:
            console.print(f"[red]✗ Error:[/red] User with ID '{user_id}' not found", style="red")
            raise typer.Exit(1)
        except HttpResponseError as e:
            console.print(f"[red]✗ Azure Table Storage error:[/red] {e}", style="red")
            raise typer.Exit(1)
        
        # Confirm deletion
        if not force:
            console.print(f"\n[yellow]About to delete:[/yellow]")
            console.print(f"  User Name: {user_name}")
            console.print(f"  User ID: {user_id}")
            
            confirm = typer.confirm("\nAre you sure you want to delete this user?")
            if not confirm:
                console.print("\n[yellow]Cancelled[/yellow]\n")
                raise typer.Exit(0)
        
        # Delete user
        try:
            table_client.delete_entity("user", user_id)
            console.print(f"\n[green]✓ User '{user_name}' (ID: {user_id}) deleted successfully[/green]\n")
        except HttpResponseError as e:
            console.print(f"[red]✗ Error deleting user:[/red] {e}", style="red")
            raise typer.Exit(1)
        
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[red]✗ Unexpected error:[/red] {e}", style="red")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
