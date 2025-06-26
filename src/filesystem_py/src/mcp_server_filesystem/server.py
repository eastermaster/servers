from __future__ import annotations

import json
import os
from collections import deque
from enum import Enum
from pathlib import Path
from typing import Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from pydantic import BaseModel, Field


class FsTools(str, Enum):
    READ_FILE = "read_file"
    READ_MULTIPLE_FILES = "read_multiple_files"
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    CREATE_DIRECTORY = "create_directory"
    LIST_DIRECTORY = "list_directory"
    MOVE_FILE = "move_file"
    SEARCH_FILES = "search_files"
    GET_FILE_INFO = "get_file_info"
    LIST_ALLOWED_DIRECTORIES = "list_allowed_directories"


class ReadFile(BaseModel):
    path: str
    tail: int | None = Field(
        default=None,
        description="Return only the last N lines of the file",
        ge=1,
    )
    head: int | None = Field(
        default=None,
        description="Return only the first N lines of the file",
        ge=1,
    )


class ReadMultipleFiles(BaseModel):
    paths: list[str]


class WriteFile(BaseModel):
    path: str
    content: str


class EditOperation(BaseModel):
    oldText: str
    newText: str


class EditFile(BaseModel):
    path: str
    edits: list[EditOperation]
    dryRun: bool = False


class CreateDirectory(BaseModel):
    path: str


class ListDirectory(BaseModel):
    path: str


class MoveFile(BaseModel):
    source: str
    destination: str


class SearchFiles(BaseModel):
    path: str
    pattern: str


class GetFileInfo(BaseModel):
    path: str


async def serve(directories: Sequence[str]) -> None:
    allowed_dirs = [Path(os.path.expanduser(d)).resolve() for d in directories]
    for d in allowed_dirs:
        if not d.is_dir():
            raise ValueError(f"{d} is not a directory")

    def validate_path(p: str) -> Path:
        abs_path = Path(os.path.expanduser(p)).resolve()
        for d in allowed_dirs:
            try:
                abs_path.relative_to(d)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Access denied: {abs_path}")
        return abs_path

    def tail_file(path: Path, n: int) -> str:
        q: deque[str] = deque(maxlen=n)
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                q.append(line.rstrip("\n"))
        return "\n".join(q)

    def head_file(path: Path, n: int) -> str:
        lines: list[str] = []
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for _ in range(n):
                line = f.readline()
                if not line:
                    break
                lines.append(line.rstrip("\n"))
        return "\n".join(lines)

    server = Server("mcp-filesystem-py")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=FsTools.READ_FILE, description="Read a file", inputSchema=ReadFile.model_json_schema()),
            Tool(name=FsTools.READ_MULTIPLE_FILES, description="Read multiple files", inputSchema=ReadMultipleFiles.model_json_schema()),
            Tool(name=FsTools.WRITE_FILE, description="Write a file", inputSchema=WriteFile.model_json_schema()),
            Tool(name=FsTools.EDIT_FILE, description="Edit a file", inputSchema=EditFile.model_json_schema()),
            Tool(name=FsTools.CREATE_DIRECTORY, description="Create a directory", inputSchema=CreateDirectory.model_json_schema()),
            Tool(name=FsTools.LIST_DIRECTORY, description="List directory", inputSchema=ListDirectory.model_json_schema()),
            Tool(name=FsTools.MOVE_FILE, description="Move a file", inputSchema=MoveFile.model_json_schema()),
            Tool(name=FsTools.SEARCH_FILES, description="Search files", inputSchema=SearchFiles.model_json_schema()),
            Tool(name=FsTools.GET_FILE_INFO, description="Get file information", inputSchema=GetFileInfo.model_json_schema()),
            Tool(name=FsTools.LIST_ALLOWED_DIRECTORIES, description="List allowed directories", inputSchema={"type": "object", "properties": {}}),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            match name:
                case FsTools.READ_FILE:
                    args = ReadFile(**arguments)
                    file_path = validate_path(args.path)
                    if args.tail:
                        text = tail_file(file_path, args.tail)
                    elif args.head:
                        text = head_file(file_path, args.head)
                    else:
                        text = file_path.read_text(encoding="utf-8", errors="ignore")
                    return [TextContent(type="text", text=text)]
                case FsTools.READ_MULTIPLE_FILES:
                    args = ReadMultipleFiles(**arguments)
                    outputs = []
                    for p in args.paths:
                        try:
                            fp = validate_path(p)
                            outputs.append({"path": p, "content": fp.read_text(encoding="utf-8", errors="ignore")})
                        except Exception as e:
                            outputs.append({"path": p, "error": str(e)})
                    return [TextContent(type="text", text=json.dumps(outputs, indent=2))]
                case FsTools.WRITE_FILE:
                    args = WriteFile(**arguments)
                    file_path = validate_path(args.path)
                    file_path.write_text(args.content, encoding="utf-8")
                    return [TextContent(type="text", text=f"Wrote {args.path}")]
                case FsTools.EDIT_FILE:
                    args = EditFile(**arguments)
                    file_path = validate_path(args.path)
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    new_content = content
                    for edit in args.edits:
                        if edit.oldText not in new_content:
                            raise ValueError(f"oldText not found: {edit.oldText}")
                        new_content = new_content.replace(edit.oldText, edit.newText, 1)
                    if args.dryRun:
                        import difflib

                        diff = "\n".join(
                            difflib.unified_diff(
                                content.splitlines(),
                                new_content.splitlines(),
                                fromfile="before",
                                tofile="after",
                            )
                        )
                        return [TextContent(type="text", text=diff)]
                    file_path.write_text(new_content, encoding="utf-8")
                    return [TextContent(type="text", text="Edits applied")]
                case FsTools.CREATE_DIRECTORY:
                    args = CreateDirectory(**arguments)
                    dir_path = validate_path(args.path)
                    dir_path.mkdir(parents=True, exist_ok=True)
                    return [TextContent(type="text", text=f"Created {args.path}")]
                case FsTools.LIST_DIRECTORY:
                    args = ListDirectory(**arguments)
                    dir_path = validate_path(args.path)
                    entries = []
                    for entry in sorted(dir_path.iterdir()):
                        prefix = "[DIR]" if entry.is_dir() else "[FILE]"
                        entries.append(f"{prefix} {entry.name}")
                    return [TextContent(type="text", text="\n".join(entries))]
                case FsTools.MOVE_FILE:
                    args = MoveFile(**arguments)
                    src = validate_path(args.source)
                    dst = validate_path(args.destination)
                    src.rename(dst)
                    return [TextContent(type="text", text=f"Moved {args.source} to {args.destination}")]
                case FsTools.SEARCH_FILES:
                    args = SearchFiles(**arguments)
                    root = validate_path(args.path)
                    results = []
                    for dirpath, dirnames, filenames in os.walk(root):
                        for name in filenames + dirnames:
                            if args.pattern.lower() in name.lower():
                                full = Path(dirpath) / name
                                try:
                                    validate_path(str(full))
                                    results.append(str(full))
                                except Exception:
                                    pass
                    return [TextContent(type="text", text="\n".join(results))]
                case FsTools.GET_FILE_INFO:
                    args = GetFileInfo(**arguments)
                    file_path = validate_path(args.path)
                    stat = file_path.stat()
                    info = {
                        "size": stat.st_size,
                        "created": stat.st_ctime,
                        "modified": stat.st_mtime,
                        "accessed": stat.st_atime,
                        "is_directory": file_path.is_dir(),
                        "is_file": file_path.is_file(),
                    }
                    return [TextContent(type="text", text=json.dumps(info, indent=2))]
                case FsTools.LIST_ALLOWED_DIRECTORIES:
                    return [TextContent(type="text", text="\n".join(str(d) for d in allowed_dirs))]
                case _:
                    raise ValueError(f"Unknown tool: {name}")
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)
