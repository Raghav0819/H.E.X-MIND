from mcp.server.fastmcp import FastMCP
server = FastMCP("mini")
@server.tool()
def read_file(path: str) -> str:
    """Read a file."""
    return f"contents of {path}"
@server.tool()
def git_status() -> str:
    """Show git status."""
    return "clean"
server.run("stdio")
