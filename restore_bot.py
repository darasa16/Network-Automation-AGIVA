import json
import os
import sys
import re

full_transcript_path = r'C:\Users\LENOVO FLEX 7\.gemini\antigravity-ide\brain\3e89b3eb-642c-43c9-af1f-54a79506ceb0\.system_generated\logs\transcript_full.jsonl'

try:
    with open(full_transcript_path, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            content = data.get('content', '')
            if data.get('type') == 'TOOL_RESPONSE' and 'Total Lines: 798' in content and 'bot.py' in content:
                print('Found the file in full transcript!')
                # Extract the lines
                lines = content.split('\n')
                code_lines = []
                for cl in lines:
                    match = re.match(r'^\d+:\s(.*)', cl)
                    if match:
                        code_lines.append(match.group(1))
                    elif re.match(r'^\d+:$', cl.strip()):
                        code_lines.append('')
                
                if len(code_lines) > 500:
                    with open('bot_restored.py', 'w', encoding='utf-8') as out:
                        out.write('\n'.join(code_lines))
                    print(f'Restored {len(code_lines)} lines to bot_restored.py')
                    sys.exit(0)
except Exception as e:
    print('Error:', e)
