#!/usr/bin/env python3
"""
Simple MCP GitHub Server - Single Repository Focus
"""

import asyncio
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
        self.session = aiohttp.ClientSession() #aiohttp is needed for reusing of the single sesison.

    async def close_session(self):
        if self.session:
            await self.session.close()

    def get_headers(self): #this function build a proper headers to communicate with the github api.
        headers = {'Accept': 'application/vnd.github.v3+json'} #it is for the github so that it respond as per github api version 3.
        if self.github_token:
            headers['Authorization'] = f'token {self.github_token}' 
        return headers

    async def get_repo_contents(self, owner, repo, path=""):
        url = f'https://api.github.com/repos/{owner}/{repo}/contents/{path}'
        async with self.session.get(url, headers=self.get_headers()) as response:
            if response.status == 200:
                return await response.json()
            return []

    async def get_file_content(self, owner, repo, path):
        url = f'https://api.github.com/repos/{owner}/{repo}/contents/{path}'
        async with self.session.get(url, headers=self.get_headers()) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('content'):
                    return base64.b64decode(data['content']).decode('utf-8', errors='ignore')
            return ""

    async def get_repo_tree(self, owner, repo):
        """Get all files in repository recursively"""
        url = f'https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD'
        params = {'recursive': '1'}
        
        async with self.session.get(url, headers=self.get_headers(), params=params) as response:
            if response.status == 200:
                tree_data = await response.json()
                return tree_data.get('tree', [])
            return []

    async def get_specific_repo_data(self, username, repo_name):
        repo_data = {"username": username, "repository": repo_name, "files": []}
        
        # Get all files in the repository
        tree = await self.get_repo_tree(username, repo_name)
        
        # Filter for code files and get their content
        for item in tree:
            if item['type'] == 'blob' and item['path'].endswith(('.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.md', '.txt', '.json', '.yaml', '.yml', '.html', '.css', '.sql')):
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
                        'tools': [{
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
                        }]
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