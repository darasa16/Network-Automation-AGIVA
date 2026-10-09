import re

with open('templates/index.html', 'r', encoding='utf-8') as f:
    text = f.read()

table_match = re.search(r'(\s*<div class="table-panel" id="monitored-devices">.*?\s*</table>\s*</div>\s*</div>)', text, re.DOTALL)
if table_match:
    table_content = table_match.group(1)
    text = text.replace(table_content, '')
    
    insert_point_match = re.search(r'(\s*</div>\s*<aside class="alerts-sidebar">)', text)
    if insert_point_match:
        replacement = table_content + insert_point_match.group(1)
        text = text.replace(insert_point_match.group(1), replacement)
        
        with open('templates/index.html', 'w', encoding='utf-8') as f:
            f.write(text)
        print('Fixed layout!')
    else:
        print('Could not find insert point')
else:
    print('Could not find table panel')
