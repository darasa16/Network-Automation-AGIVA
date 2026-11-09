import os, sys, re

sys.stdout.reconfigure(encoding='utf-8')
from check_indonesian import indonesian_keywords, pattern

for path in ['app.py', 'backup_service.py', 'bot.py', 'collector.py', 'rule_engine.py']:
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for idx, line in enumerate(f, 1):
            s = line.strip()
            if ('"' in s or "'" in s) and not s.startswith(('#', '*')):
                matches = pattern.findall(s)
                if matches:
                    # filter out docstrings if needed, or print
                    print(f"{path}:{idx}: {set(matches)} -> {s[:130]}")

