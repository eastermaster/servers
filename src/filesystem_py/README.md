# Filesystem MCP Server (Python)

This package provides a reference implementation of the Model Context Protocol filesystem server written in Python. The server exposes a set of filesystem tools for use by an MCP client.

```
pip install mcp-server-filesystem-py
python -m mcp_server_filesystem --dir /path/to/allowed
```

The server restricts all operations to the directories provided on the command line.
