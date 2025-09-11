#!/usr/bin/env python3
"""
FastMCP GitHub Server with JSON-RPC 2.0. used under the hood.
"""

import sys
import asyncio
import json
import os
import aiohttp
import base64
import signal
from fastmcp import FastMCP

# Load environment variables in server process
from dotenv import load_dotenv
load_dotenv()

# Create FastMCP server instance
mcp = FastMCP("GitHub Repository Explorer")

class GitHubService:
    def __init__(self):
        # Validate required environment variables
        self.github_token = os.getenv('GITHUB_TOKEN')
        if not os.getenv('GOOGLE_API_KEY'):
            print("Warning: GOOGLE_API_KEY not found in environment", file=sys.stderr)
        
        self.session = None
        self._session_lock = asyncio.Lock()
        
    async def ensure_session(self):
        """Ensure session exists with proper locking"""
        if not self.session or self.session.closed:
            async with self._session_lock:
                if not self.session or self.session.closed:
                    self.session = aiohttp.ClientSession() #it starts a session in a lock so that only one session can be started at a time.
        
    async def close_session(self):
        """Properly close session"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    def get_headers(self):
        headers = {'Accept': 'application/vnd.github.v3+json'} #It asks for the data in github version 3 JSON.
        if self.github_token:
            headers['Authorization'] = f'token {self.github_token}'
        return headers

    async def get_file_content(self, owner, repo, path):
        """Fixed version with proper session management and encoding handling"""
        await self.ensure_session()
        url = f'https://api.github.com/repos/{owner}/{repo}/contents/{path}'
        
        try:
            async with self.session.get(url, headers=self.get_headers()) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('content'):
                        try:
                            content = base64.b64decode(data['content']).decode('utf-8') #data['content'] is in base64 encoded eg "cHJpbnQoIkhlbGxvLCBHaXRIdWIhIikK" and then base64.b64decode(data['content']) decoded to normal string eg. b'print("Hello, GitHub!")\n' it is still not string but .decode('utf-8') makes it print("Hello, GitHub!") which was the actual content on server.
                            return content
                        except UnicodeDecodeError:
                            # Try different encodings instead of ignoring errors
                            for encoding in ['latin1', 'cp1252', 'iso-8859-1']:
                                try:
                                    return base64.b64decode(data['content']).decode(encoding)
                                except:
                                    continue
                            # Last resort: decode with error replacement
                            return base64.b64decode(data['content']).decode('utf-8', errors='replace')
                elif response.status == 404:
                    print(f"File not found: {path}")
                    return ""
                elif response.status == 403:
                    print(f"API rate limit exceeded or forbidden: {path}")
                    return ""
                else:
                    print(f"GitHub API error {response.status} for {path}")
                    return ""
        except Exception as e:
            print(f"Error fetching {path}: {e}")
            return ""

    async def get_repo_tree(self, owner, repo):
        """Fixed version with proper error handling"""
        await self.ensure_session()
        url = f'https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD'
        params = {'recursive': '1'}     #it tells github, Give me the full repo tree (all subfolders and files), not just the top folder.
        
        try:
            async with self.session.get(url, headers=self.get_headers(), params=params) as response:
                if response.status == 200:
                    tree_data = await response.json()
                    return tree_data.get('tree', [])
                elif response.status == 404:
                    print(f"Repository not found: {owner}/{repo}")
                    return []
                elif response.status == 403:
                    print(f"API rate limit exceeded or repository access forbidden: {owner}/{repo}")
                    return []
                else:
                    print(f"GitHub API error {response.status} for repo tree")
                    return []
        except Exception as e:
            print(f"Error fetching repo tree: {e}")
            return []

    '''sample output of github for tree calling:
        {
        "sha": "abc123",
        "tree": [
            {"path": "README.md", "type": "blob", "size": 1200},
            {"path": "src/main.c", "type": "blob", "size": 5400},
            {"path": "docs/", "type": "tree"}
        ],
        "truncated": false
        }
        where this get_repo_tree returns only "tree" array.
    
    '''

    async def get_specific_repo_data(self, username, repo_name):
        """Fixed version with memory management and batch processing"""
        repo_data = {"username": username, "repository": repo_name, "files": []}
        
        # Get all files in the repository
        tree = await self.get_repo_tree(username, repo_name)
        if not tree:
            return {"error": f"Could not fetch repository data for {username}/{repo_name}. Check if repository exists and is accessible."}
        
        # Process files in batches to prevent memory issues and rate limiting
        batch_size = 5  # Reduced batch size to be gentler on API
        processed = 0
        total_files = len([item for item in tree if item['type'] == 'blob' and 
                          item['path'].endswith(('.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.md', '.txt', '.json', '.yaml', '.yml', '.html', '.css', '.sql', '.csv')) and 
                          item['size'] < 50000])
        
        print(f"Processing {total_files} files from repository...")
        
        for item in tree:
            if item['type'] == 'blob' and item['path'].endswith(('.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.md', '.txt', '.json', '.yaml', '.yml', '.html', '.css', '.sql', '.csv')):
                if item['size'] < 50000:  # Skip very large files
                    content = await self.get_file_content(username, repo_name, item['path'])
                    if content.strip():  # Only add non-empty files
                        repo_data['files'].append({
                            'path': item['path'],
                            'content': content,
                            'size': item['size']
                        })
                    
                    processed += 1
                    if processed % batch_size == 0:
                        # Delay to prevent overwhelming the API
                        await asyncio.sleep(0.2)
                        print(f"Processed {processed}/{total_files} files...")
        
        print(f"Successfully loaded {len(repo_data['files'])} files")
        return repo_data

# Create a global service instance
github_service = GitHubService()

@mcp.tool()
async def get_repo_data(username: str, repo_name: str) -> str:
    """Get specific repository data with all files (with proper error handling and rate limiting)
    
    Args:
        username: GitHub username
        repo_name: Repository name
    
    Returns:
        JSON string containing repository data with all files
    """
    try:
        result = await github_service.get_specific_repo_data(username, repo_name)
        return json.dumps(result)
    except Exception as e:
        error_result = {"error": f"Failed to fetch repository data: {str(e)}"}
        return json.dumps(error_result)

@mcp.tool()
async def get_file_content(username: str, repo_name: str, file_path: str) -> str:
    """Get content of a specific file (with proper encoding handling)
    
    Args:
        username: GitHub username
        repo_name: Repository name
        file_path: Path to the file in the repository
    
    Returns:
        File content as string
    """
    try:
        content = await github_service.get_file_content(username, repo_name, file_path)
        return content if content else f"File '{file_path}' not found or is empty"
    except Exception as e:
        return f"Error fetching file '{file_path}': {str(e)}"

# Graceful shutdown handling
async def cleanup():
    """Cleanup function for graceful shutdown"""
    print("Cleaning up GitHub service...")
    await github_service.close_session()

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    print(f"\nReceived signal {signum}, shutting down gracefully...")
    asyncio.create_task(cleanup())
    exit(0)

if __name__ == '__main__':
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Validate environment on startup
    if not os.getenv('GITHUB_TOKEN'):
        print("Warning: GITHUB_TOKEN not found. API rate limits will be lower (60/hour vs 5000/hour)", file=sys.stderr)
    
    try:
        mcp.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
        asyncio.run(cleanup())
    except Exception as e:
        print(f"Server error: {e}", file=sys.stderr)
        asyncio.run(cleanup())
        exit(1)
