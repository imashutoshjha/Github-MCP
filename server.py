#!/usr/bin/env python3
"""
Simple MCP GitHub Server - Single Repository Focus
"""

import asyncio  #Async HTTP client library — used for making asynchronous calls to the GitHub API.
import json
import sys
import os
import aiohttp
import base64

class GitHubMCPServer:
    def __init__(self):
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.session = None
        
    async def start_session(self):
        self.session = aiohttp.ClientSession()

    async def close_session(self):
        if self.session:
            await self.session.close()

    def get_headers(self): #this function will create a headers dictionary which will have 'Accept', 'Authorizaton'
        headers = {'Accept': 'application/vnd.github.v3+json'}
        if self.github_token:
            headers['Authorization'] = f'token {self.github_token}' 
        return headers

    async def get_file_content(self, owner, repo, path): #this will return a dictionary having keys of name,path,sha,size,url,download_url,type,content,encoding
        url = f'https://api.github.com/repos/{owner}/{repo}/contents/{path}'
        async with self.session.get(url, headers=self.get_headers()) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('content'):
                    return base64.b64decode(data['content']).decode('utf-8', errors='ignore')
            return ""

    async def get_repo_tree(self, owner, repo): #it returns the entire repo file trees ie. list of dicts
        """Get all files in repository recursively"""
        url = f'https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD'
        params = {'recursive': '1'} #It say don’t just give me top-level files, give me the entire tree (all subfolders, all files).
        
        async with self.session.get(url, headers=self.get_headers(), params=params) as response:
            if response.status == 200:
                tree_data = await response.json()
                return tree_data.get('tree', [])
            return []

    async def get_specific_repo_data(self, username, repo_name):
        repo_data = {"username": username, "repository": repo_name, "files": []}
        
        # Get all files in the repository
        tree = await self.get_repo_tree(username, repo_name)
        
        # Filter for code files and get their content - Including CSV files
        for item in tree:
            if item['type'] == 'blob' and item['path'].endswith(('.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.md', '.txt', '.json', '.yaml', '.yml', '.html', '.css', '.sql', '.csv')):
                if item['size'] < 50000:  # Skip very large files
                    content = await self.get_file_content(username, repo_name, item['path'])
                    if content:
                        repo_data['files'].append({
                            'path': item['path'],
                            'content': content,
                            'size': item['size']
                        })
        
        return repo_data

    async def handle_request(self, request):
        method = request.get('method')
        params = request.get('params', {})
        request_id = request.get('id')

        try:
            if method == 'initialize':
                return {
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'result': {'capabilities': {'tools': {}}}
                }
            
            elif method == 'tools/list':
                return {
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'result': {
                        'tools': [
                            {
                                'name': 'get_repo_data',
                                'description': 'Get specific repository data with all files',
                                'inputSchema': {
                                    'type': 'object',
                                    'properties': {
                                        'username': {'type': 'string'},
                                        'repo_name': {'type': 'string'}
                                    },
                                    'required': ['username', 'repo_name']
                                }
                            },
                            {
                                'name': 'get_file_content',
                                'description': 'Get content of a specific file',
                                'inputSchema': {
                                    'type': 'object',
                                    'properties': {
                                        'username': {'type': 'string'},
                                        'repo_name': {'type': 'string'},
                                        'file_path': {'type': 'string'}
                                    },
                                    'required': ['username', 'repo_name', 'file_path']
                                }
                            }
                        ]
                    }
                }
            
            elif method == 'tools/call':
                tool_name = params.get('name')
                arguments = params.get('arguments', {})
                
                if tool_name == 'get_repo_data':
                    result = await self.get_specific_repo_data(arguments['username'], arguments['repo_name'])
                    return {
                        'jsonrpc': '2.0',
                        'id': request_id,
                        'result': {
                            'content': [{'type': 'text', 'text': json.dumps(result)}]
                        }
                    }
                elif tool_name == 'get_file_content':
                    content = await self.get_file_content(arguments['username'], arguments['repo_name'], arguments['file_path'])
                    return {
                        'jsonrpc': '2.0',
                        'id': request_id,
                        'result': {
                            'content': [{'type': 'text', 'text': content}]
                        }
                    }
        
        except Exception as e:
            return {
                'jsonrpc': '2.0',
                'id': request_id,
                'error': {'code': -1, 'message': str(e)}
            }

    async def run_stdio(self):
        await self.start_session()
        
        try:
            while True:
                line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                
                try:
                    request = json.loads(line.strip())
                    response = await self.handle_request(request)
                    print(json.dumps(response), flush=True)
                except:
                    continue
        finally:
            await self.close_session()

if __name__ == '__main__':
    server = GitHubMCPServer()
    asyncio.run(server.run_stdio())
