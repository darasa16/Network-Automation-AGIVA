import json
import sys

full_transcript_path = r'C:\Users\LENOVO FLEX 7\.gemini\antigravity-ide\brain\3e89b3eb-642c-43c9-af1f-54a79506ceb0\.system_generated\logs\transcript_full.jsonl'

try:
    with open(full_transcript_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            data = json.loads(line)
            if data.get('type') == 'TOOL_RESPONSE':
                content = data.get('content')
                if content and isinstance(content, str) and 'Total Lines: 798' in content:
                    print('Found in content at line', i)
                    with open('transcript_match.txt', 'w', encoding='utf-8') as out:
                        out.write(content)
                    sys.exit(0)
except Exception as e:
    print('Error:', e)
