#!/usr/bin/env python3
"""
FastMCP GitHub Client - FIXED VERSION
"""

import asyncio
import json
import sys
import os
import re
import signal
from dotenv import load_dotenv
import google.generativeai as genai
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class GitHubFastMCPClient:
    def __init__(self, server_script):
        load_dotenv()
        self.server_script = server_script
        self.session = None
        
        # Validate required environment variables
        google_api_key = os.getenv('GOOGLE_API_KEY')
        if not google_api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment. Please set it in your .env file.")
        
        # Configure Gemini with error handling
        try:
            genai.configure(api_key=google_api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        except Exception as e:
            raise ValueError(f"Failed to configure Google Gemini: {e}")
        
        self.system_message = "You are a helpful coding assistant with access to the user's GitHub repository."
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
        
        # Enhanced content analysis
        if file_ext == '.py':
            summary['functions'] = re.findall(r'def\s+(\w+)\s*\(', content)
            summary['classes'] = re.findall(r'class\s+(\w+)\s*[\(:]', content)
            summary['imports'] = re.findall(r'(?:from\s+\S+\s+)?import\s+([^\n]+)', content)
            
        elif file_ext == '.csv':
            lines = content.split('\n')
            if lines and lines[0].strip():
                summary['description'] = f'CSV data file with columns: {lines[0].strip()}'
                summary['rows'] = len([line for line in lines if line.strip()]) - 1
                
        # Enhanced description generation based on filename and content
        filename_lower = file_path.lower()
        if 'main' in filename_lower or '__main__' in content:
            summary['description'] = 'Main application entry point'
        elif 'test' in filename_lower:
            summary['description'] = 'Test file or testing data'
        elif 'train' in filename_lower:
            summary['description'] = 'Training data or training script'
        elif 'model' in filename_lower:
            summary['description'] = 'Machine learning model or data model'
        elif file_ext == '.csv' and not summary['description']:
            summary['description'] = 'Data file in CSV format'
        elif file_ext == '.md':
            summary['description'] = 'Documentation file'
        elif file_ext == '.json':
            summary['description'] = 'Configuration or data file in JSON format'
        elif 'config' in filename_lower:
            summary['description'] = 'Configuration file'
        
        return summary

    def generate_fresh_cache(self, repo_data, username, repo_name):
        """Generate fresh repository summary cache with error handling"""
        print("🔄 Generating fresh repository analysis...")
        
        if 'error' in repo_data:
            print(f"❌ Cannot generate cache: {repo_data['error']}")
            return None
        
        cache_data = {
            'username': username,
            'repo_name': repo_name,
            'total_files': len(repo_data.get('files', [])),
            'file_summaries': [],
            'file_types': {}
        }
        
        for file_info in repo_data.get('files', []):
            try:
                file_summary = self.analyze_file_content(file_info['path'], file_info['content'])
                cache_data['file_summaries'].append(file_summary)
                
                file_type = file_summary['type'] or 'no-extension'
                cache_data['file_types'][file_type] = cache_data['file_types'].get(file_type, 0) + 1
            except Exception as e:
                print(f"Warning: Error analyzing {file_info.get('path', 'unknown')}: {e}")
        
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            print(f"💾 Generated fresh summary with {cache_data['total_files']} files")
        except Exception as e:
            print(f"Warning: Could not save cache file: {e}")
        
        return cache_data

    async def get_repo_data(self, username, repo_name):
        """Call the FastMCP tool to get repository data with better error handling"""
        try:
            result = await self.session.call_tool("get_repo_data", {
                "username": username,
                "repo_name": repo_name
            })
            
            if result.content and len(result.content) > 0:
                content_text = result.content[0].text
                return json.loads(content_text)
            else:
                raise Exception("No content in response from FastMCP server")
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON response from server: {e}")
        except Exception as e:
            raise Exception(f"Failed to get repo data: {e}")

    async def get_file_content(self, username, repo_name, file_path):
        """Get content of a specific file with better error handling"""
        try:
            result = await self.session.call_tool("get_file_content", {
                "username": username,
                "repo_name": repo_name,
                "file_path": file_path
            })
            
            if result.content and len(result.content) > 0:
                return result.content[0].text
            else:
                print(f"Warning: No content returned for {file_path}")
                return ""
        except Exception as e:
            print(f"Error getting file content for {file_path}: {e}")
            return ""

    async def llm_call_decide_files(self, user_question, summary_json):
        """LLM Call 1: Decide which files are relevant with improved parsing"""
        prompt = f"""Based on the user question and repository summary, identify the most relevant files.

Repository Summary:
{json.dumps(summary_json, indent=2)}

User Question: {user_question}

Respond with ONLY the file paths that are most relevant, separated by commas. For example:
file1.py,file2.csv,file3.md

Important: Only return file paths that exist in the repository summary above.

File paths only:"""

        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Improved parsing - handle various formats LLM might return
            lines = response_text.split('\n')
            file_line = ""
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('-') and ',' in line:
                    file_line = line
                    break
            
            if not file_line:
                # Fallback: take the last non-empty line
                file_line = next((line.strip() for line in reversed(lines) if line.strip()), response_text)
            
            # Parse file paths
            file_paths = [path.strip().strip('`"\'') for path in file_line.split(',') if path.strip()]
            
            # Validate file paths exist in summary
            available_files = [f['path'] for f in summary_json.get('file_summaries', [])]
            valid_files = [f for f in file_paths if f in available_files]
            
            if not valid_files and file_paths:
                print(f"⚠️ LLM suggested files not found in repo: {file_paths}")
                # Fallback: return first few files from repo
                valid_files = available_files[:3]
            
            return valid_files[:5]  # Limit to 5 files max
        except Exception as e:
            print(f"❌ Error in LLM file selection: {e}")
            # Fallback: return first few files
            return [f['path'] for f in summary_json.get('file_summaries', [])][:3]

    async def llm_call_final_answer(self, user_question, summary_json, files_content):
        """Enhanced LLM call for final answer with better context building"""
        
        # Build focused, well-structured context
        context_parts = [f"User question: {user_question}\n"]
        
        # Add repository overview
        context_parts.append(f"Repository: {summary_json.get('username', 'unknown')}/{summary_json.get('repo_name', 'unknown')}")
        context_parts.append(f"Total files analyzed: {summary_json.get('total_files', 0)}\n")
        
        # Add file contents with better formatting
        for file_path, content in files_content.items():
            if content and content.strip():
                context_parts.append(f"=== FILE: {file_path} ===")
                # Limit content length to prevent token overflow
                truncated_content = content[:5000] + "..." if len(content) > 5000 else content
                context_parts.append(truncated_content)
                context_parts.append(f"=== END FILE: {file_path} ===\n")
        
        final_context = "\n".join(context_parts)
        
        # Improved prompt with specific instructions
        prompt = f"""You are a code analysis expert. Analyze the following repository files and provide a comprehensive answer to the user's question.

{final_context}

Instructions:
- Provide specific, detailed explanations based on the actual code content
- Reference specific functions, classes, or code sections when relevant
- If files appear empty or problematic, mention this clearly
- Focus on answering the user's specific question
- Be thorough but concise

Answer:"""

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"❌ Error generating response: {str(e)}"

    async def run_session(self, username, repo_name):
        """Run the client session with proper context management"""
        # Pass environment variables to server subprocess
        env = os.environ.copy()
        env['GITHUB_TOKEN'] = os.getenv('GITHUB_TOKEN')
        env['GOOGLE_API_KEY'] = os.getenv('GOOGLE_API_KEY')
        
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[self.server_script],
            env=env
        )
        
        print(f"🚀 Starting FastMCP session and loading repository: {username}/{repo_name}...")
        
        # FIXED: Proper context manager usage
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self.session = session
                
                print("✅ FastMCP session initialized successfully")
                
                # Always fetch fresh repo data
                print("🔄 Fetching latest repo data...")
                repo_data = await self.get_repo_data(username, repo_name)
                
                # Handle error responses
                if 'error' in repo_data:
                    print(f"❌ Error: {repo_data['error']}")
                    return
                
                # Generate fresh cache every time
                summary_json = self.generate_fresh_cache(repo_data, username, repo_name)
                if not summary_json:
                    print("❌ Failed to generate repository summary")
                    return
                
                print(f"✅ Repository '{repo_name}' loaded successfully!")
                print(f"📁 Analyzed {summary_json['total_files']} files")
                
                # Show file type breakdown
                if summary_json.get('file_types'):
                    print(f"📊 File types: {dict(list(summary_json['file_types'].items())[:5])}")
                
                print("\n🤖 I'm ready to help! Ask me anything about your code.")
                print("Examples:")
                print("- 'What does my repo do?'")
                print("- 'Explain my dataset'")
                print("- 'Tell me about main.py'") 
                print("- 'Show me important functions'")
                print("- 'What are the CSV files about?'")
                print("\nType 'quit' to exit.\n")
                
                while True:
                    try:
                        user_input = input("You: ").strip()
                        
                        if user_input.lower() in ['quit', 'exit', 'q']:
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
                            
                            # Step 2: Fetch actual file content
                            files_content = {}
                            for file_path in relevant_files:
                                content = await self.get_file_content(username, repo_name, file_path)
                                files_content[file_path] = content
                                print(f"   📄 {file_path}: {len(content)} chars, {len(content.strip())} non-whitespace")
                            
                            print("🧠 Step 3: Generating final answer...")
                            
                            # Step 3: LLM generates final answer
                            final_answer = await self.llm_call_final_answer(user_input, summary_json, files_content)
                            
                            print(f"\n🤖 AI: {final_answer}\n")
                            
                    except KeyboardInterrupt:
                        print("\n👋 Goodbye!")
                        break
                    except Exception as e:
                        print(f"❌ Error processing question: {e}")
                        continue

    async def run(self, username, repo_name):
        """Main run method with comprehensive error handling"""
        try:
            await self.run_session(username, repo_name)
        except Exception as e:
            print(f"❌ Error running client: {e}")

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    print(f"\n🛑 Received signal {signum}, shutting down...")
    sys.exit(0)

if __name__ == '__main__':
    # Setup signal handling
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    if len(sys.argv) != 4:
        print("Usage: python client.py <server_script> <github_username> <repo_name>")
        print("Example: python client.py server.py octocat Hello-World")
        sys.exit(1)
    
    try:
        client = GitHubFastMCPClient(sys.argv[1])
        asyncio.run(client.run(sys.argv[2], sys.argv[3]))
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
