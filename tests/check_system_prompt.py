#!/usr/bin/env python3
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from core.system_prompt import build_system_message

system_msg = build_system_message(user_message=None)  # Test without user
content = system_msg['content']

# Check if FACTS_USED instruction is present
if 'FACTS_USED' in content:
    print('✓ FACTS_USED instruction found in system prompt')
    # Find and show the relevant section
    start = content.find('[RECENT FACTS]')
    if start != -1:
        end = min(start + 600, len(content))
        print('\n[RECENT FACTS] section:')
        print('=' * 80)
        print(content[start:end])
        print('=' * 80)
else:
    print('✗ FACTS_USED instruction NOT found in system prompt!')
    print('\nSearching for memory-related sections...')
    if '[RECENT FACTS]' in content:
        print('  - [RECENT FACTS] header found')
    else:
        print('  - [RECENT FACTS] header NOT found')
