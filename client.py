#!/usr/bin/env python3
"""
GitHub Client with Enhanced Debugging for Content Analysis
"""

import asyncio
import json
import sys
import os
import re
from dotenv import load_dotenv
import google.generativeai as genai

class GitHubClient:
    def __init__(self, server_script):
        load_dotenv()
        self.server_script = server_script
        self.process = None
        self.request_id = 0
        
        # Configure Gemini
        genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        self.system_message = "You are a helpful coding assistant with access to the user's GitHub repository."
        
        # Cache file for repo summary
        self.cache_file = 'repo_summary.json'

    def analyze_file_content(self, file_path, content):
        """Analyze file content and extract meaningful summary"""
        file_ext = os.path.splitext(file_path)[1].lower()
        
        summary = {
            'path': file_path,
            'type': file_ext,
            'size': len(content),
            'functions': [],
            'classes': [],
            'imports': [],
            'description': ''
        }
        
        if file_ext == '.py':
            summary['functions'] = re.findall(r'def\s+(\w+)\s*\(', content)
            summary['classes'] = re.findall(r'class\s+(\w+)\s*\(', content)
            summary['imports'] = re.findall(r'(?:from\s+\S+\s+)?import\s+([^\n]+)', content)
            
        elif file_ext == '.csv':
            lines = content.split('\n')
            if lines:
                summary['description'] = f'CSV data file with columns: {lines[0]}'
                
        # Generate description based on filename and content
        if 'main' in file_path.lower():
            summary['description'] = 'Main application entry point'
        elif 'test' in file_path.lower():
            summary['description'] = 'Test file or testing data'
        elif 'train' in file_path.lower():
            summary['description'] = 'Training data or training script'
        elif 'model' in file_path.lower():
            summary['description'] = 'Machine learning model or data model'
        elif file_ext == '.csv':
            if not summary['description']:
                summary['description'] = 'Data file in CSV format'
        elif file_ext == '.md':
            summary['description'] = 'Documentation file'
        
        return summary

    def generate_fresh_cache(self, repo_data, username, repo_name):
        """Generate fresh repository summary cache"""
        print("🔄 Generating fresh repository analysis...")
        
        cache_data = {
            'username': username,
            'repo_name': repo_name,
            'total_files': len(repo_data['files']),
            'file_summaries': [],
            'file_types': {}
        }
        
        for file_info in repo_data['files']:
            file_summary = self.analyze_file_content(file_info['path'], file_info['content'])
            cache_data['file_summaries'].append(file_summary)
            
            file_type = file_summary['type'] or 'no-extension'
            cache_data['file_types'][file_type] = cache_data['file_types'].get(file_type, 0) + 1
        
        with open(self.cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
        
        print(f"💾 Generated fresh summary with {cache_data['total_files']} files")
        return cache_data

    async def start_server(self):
        """Start the MCP server as a subprocess"""
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, self.server_script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1024*1024
        )
        await self.send_request('initialize', {})

    async def stop_server(self):
        if self.process:
            self.process.stdin.close()
            await self.process.wait()

    def get_next_id(self):
        self.request_id += 1
        return self.request_id

    async def send_request(self, method, params=None):
        request = {
            'jsonrpc': '2.0',
            'id': self.get_next_id(),
            'method': method
        }
        if params:
            request['params'] = params

        request_json = json.dumps(request) + '\n'
        self.process.stdin.write(request_json.encode())
        await self.process.stdin.drain()

        response_line = await self.process.stdout.readline()
        return json.loads(response_line.decode())

    async def get_repo_data(self, username, repo_name):
        """Call the MCP tool to get repository data"""
        response = await self.send_request('tools/call', {
            'name': 'get_repo_data',
            'arguments': {'username': username, 'repo_name': repo_name}
        })
        
        if 'result' in response and 'content' in response['result']:
            content = response['result']['content'][0]['text']
            return json.loads(content)
        else:
            raise Exception(f"Failed to get repo data: {response}")

    async def get_file_content(self, username, repo_name, file_path):
        """Get content of a specific file"""
        response = await self.send_request('tools/call', {
            'name': 'get_file_content',
            'arguments': {
                'username': username, 
                'repo_name': repo_name,
                'file_path': file_path
            }
        })
        
        if 'result' in response and 'content' in response['result']:
            return response['result']['content'][0]['text']
        else:
            return ""

    async def llm_call_decide_files(self, user_question, summary_json):
        """LLM Call 1: Decide which files are relevant"""
        prompt = f"""Based on the user question and repository summary, identify the most relevant files.

Repository Summary:
{json.dumps(summary_json, indent=2)}

User Question: {user_question}

Respond with ONLY the file paths that are most relevant, separated by commas. For example:
file1.py,file2.csv,file3.md

File paths only:"""

        try:
            response = self.model.generate_content(prompt)
            file_paths = [path.strip() for path in response.text.strip().split(',') if path.strip()]
            
            # Validate file paths exist in summary
            available_files = [f['path'] for f in summary_json['file_summaries']]
            valid_files = [f for f in file_paths if f in available_files]
            
            return valid_files[:5]  # Limit to 5 files max
        except Exception as e:
            print(f"❌ Error in LLM file selection: {e}")
            return []

    def debug_file_content(self, file_path, content):
        """Debug file content to understand what's being passed to LLM"""
        print(f"\n🔍 DEBUG ANALYSIS for {file_path}:")
        print(f"   Total length: {len(content)} characters")
        print(f"   Non-whitespace chars: {len(content.strip())}")
        print(f"   Number of lines: {len(content.split(chr(10)))}")
        
        # Show first 500 characters with escape sequences visible
        preview = repr(content[:500])
        print(f"   Content preview (raw): {preview}")
        
        if content.strip():
            print(f"   First non-empty line: {repr(next((line for line in content.split(chr(10)) if line.strip()), 'NO NON-EMPTY LINES'))}")
        else:
            print("   ⚠️ WARNING: File contains only whitespace!")
        
        return content

    async def llm_call_final_answer(self, user_question, summary_json, files_content):
        """Simplified, direct LLM call that works"""
        
        # Build minimal, focused context
        context = f"User question: {user_question}\n\n"
        
        for file_path, content in files_content.items():
            context += f"=== FILE: {file_path} ===\n"
            context += f"{content}\n"
            context += f"=== END FILE ===\n\n"
        
        # Ultra-simple, direct prompt
        prompt = f"""Analyze the following code files and answer the user's question.

        {context}

        Provide a detailed explanation of what you can see in the code above. Do not claim files are empty if they are not."""

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"❌ Error: {str(e)}"


    async def run(self, username, repo_name):
        await self.start_server()
        
        print(f"Loading repository: {username}/{repo_name}...")
        try:
            # Always fetch fresh repo data
            print("🔄 Fetching latest repo data...")
            repo_data = await self.get_repo_data(username, repo_name)
            
            # Generate fresh cache every time
            summary_json = self.generate_fresh_cache(repo_data, username, repo_name)
            
            # Store for later use
            self.username = username
            self.repo_name = repo_name
            
            print(f"✅ Repository '{repo_name}' loaded successfully!")
            print(f"📁 Analyzed {summary_json['total_files']} files")
            print("\n🤖 I'm ready to help! Ask me anything about your code.")
            print("Examples:")
            print("- 'What does my repo do?'")
            print("- 'Explain my dataset'")
            print("- 'Tell me about urls.py'") 
            print("- 'Show me important functions'")
            print("\nType 'quit' to exit.\n")
            
            while True:
                user_input = input("You: ").strip()
                
                if user_input.lower() in ['quit', 'exit']:
                    break
                    
                if user_input:
                    print("🔍 Step 1: Deciding relevant files with LLM...")
                    
                    # Step 1: LLM decides which files to fetch
                    relevant_files = await self.llm_call_decide_files(user_input, summary_json)
                    
                    if not relevant_files:
                        print("❌ No relevant files identified. Please rephrase your question.")
                        continue
                    
                    print(f"✅ LLM selected files: {relevant_files}")
                    print(f"📥 Step 2: Fetching {len(relevant_files)} files from GitHub...")
                    
                    # Step 2: Fetch actual file content with extensive debugging
                    files_content = {}
                    for file_path in relevant_files:
                        content = await self.get_file_content(username, repo_name, file_path)
                        files_content[file_path] = content
                        print(f"   📄 {file_path}: {len(content)} chars, {len(content.strip())} non-whitespace")
                    
                    print("🧠 Step 3: Generating final answer with enhanced debugging...")
                    
                    # Step 3: LLM generates final answer with extensive debugging
                    final_answer = await self.llm_call_final_answer(user_input, summary_json, files_content)
                    
                    print(f"\n🤖 AI: {final_answer}\n")
                    
        except Exception as e:
            print(f"❌ Error loading repository: {e}")
        
        await self.stop_server()

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: python client.py <server_script> <github_username> <repo_name>")
        print("Example: python client.py server.py imashutoshjha my-awesome-project")
        sys.exit(1)
    
    client = GitHubClient(sys.argv[1]) #argv[1] is server file path
    asyncio.run(client.run(sys.argv[2], sys.argv[3])) #github_user_name, repo_name
