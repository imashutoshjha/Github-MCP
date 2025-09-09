#!/usr/bin/env python3
"""
Simple GitHub Client with OpenAI integration - Single Repository Focus
"""

import asyncio
import json
import sys
import os
from dotenv import load_dotenv
import openai

class GitHubClient:
    def __init__(self, server_script):
        load_dotenv()
        self.server_script = server_script
        self.process = None
        self.request_id = 0
        self.openai_client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.messages = [
            {"role": "system", "content": "You are a helpful coding assistant. You have access to the user's specific GitHub repository and can answer questions about their code, explain functions, suggest improvements, find bugs, and help with any coding-related questions."}
        ]

    async def start_server(self):
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, self.server_script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1024*1024  # 1MB limit for large responses
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
        response = await self.send_request('tools/call', {
            'name': 'get_repo_data',
            'arguments': {'username': username, 'repo_name': repo_name}
        })
        content = response['result']['content'][0]['text']
        return json.loads(content)

    def get_ai_response(self, user_message):
        self.messages.append({"role": "user", "content": user_message})
        
        response = self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=self.messages,
            max_tokens=1500,
            temperature=0.1
        )
        
        ai_response = response.choices[0].message.content
        self.messages.append({"role": "assistant", "content": ai_response})
        return ai_response

    async def run(self, username, repo_name):
        await self.start_server()
        
        print(f"Loading repository: {username}/{repo_name}...")
        try:
            repo_data = await self.get_repo_data(username, repo_name)
            
            # Add repo context to messages
            file_summary = f"Repository: {repo_name}\nTotal files: {len(repo_data['files'])}\n"
            file_summary += "Files included:\n"
            for file_info in repo_data['files']:
                file_summary += f"- {file_info['path']} ({file_info['size']} bytes)\n"
            
            repo_context = f"""I have access to your GitHub repository '{repo_name}' with the following data:

{file_summary}

Complete repository data:
{json.dumps(repo_data, indent=2)}

I can help you with:
- Code explanations and analysis
- Finding bugs or issues
- Suggesting improvements
- Understanding specific functions
- Code reviews
- Architecture questions
- Any other questions about your code
"""
            
            self.messages.append({"role": "user", "content": repo_context})
            self.messages.append({"role": "assistant", "content": f"I've analyzed your '{repo_name}' repository! I can see {len(repo_data['files'])} files. Ask me anything about your code - I can explain functions, find issues, suggest improvements, or help with any coding questions."})
            
            print(f"✅ Repository '{repo_name}' loaded successfully!")
            print(f"📁 Analyzed {len(repo_data['files'])} files")
            print("\n🤖 I'm ready to help! Ask me anything about your code.")
            print("Examples:")
            print("- 'Explain the main function in my code'")
            print("- 'Find any bugs or issues'") 
            print("- 'How can I improve this code?'")
            print("- 'What does the file X.py do?'")
            print("\nType 'quit' to exit.\n")
            
            while True:
                user_input = input("You: ").strip()
                
                if user_input.lower() in ['quit', 'exit']:
                    break
                    
                if user_input:
                    print("🤔 Analyzing...", end=" ", flush=True)
                    response = self.get_ai_response(user_input)
                    print(f"\r🤖 AI: {response}")
                    
        except Exception as e:
            print(f"❌ Error loading repository: {e}")
        
        await self.stop_server()

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: python client.py <server_script> <github_username> <repo_name>")
        print("Example: python client.py server.py imashutoshjha my-awesome-project")
        sys.exit(1)
    
    client = GitHubClient(sys.argv[1])
    asyncio.run(client.run(sys.argv[2], sys.argv[3]))