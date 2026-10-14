"""Fix UTF-8 mojibake in HTML template caused by PowerShell Set-Content encoding mismatch."""
import sys

path = 'ui/templates/team_admin_onboarding.html'

with open(path, 'r', encoding='utf-8-sig') as f:  # utf-8-sig strips BOM
    content = f.read()

# Fix mojibake: PowerShell read UTF-8 bytes as CP1252 then saved as UTF-8.
# Reverse: encode the garbled string back to CP1252 bytes, then decode as UTF-8.
# Characters that can't be encoded as CP1252 are left unchanged (they're correct).
result_chars = []
i = 0
while i < len(content):
    # Try to find a run of characters that are all CP1252-encodable
    # and when re-encoded produce valid UTF-8 sequences.
    # Simple approach: try each char individually, collect runs, decode.
    run_bytes = bytearray()
    j = i
    while j < len(content):
        c = content[j]
        try:
            b = c.encode('cp1252')
            run_bytes.extend(b)
            j += 1
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
    
    if run_bytes:
        # Try to decode the collected bytes as UTF-8
        try:
            decoded = run_bytes.decode('utf-8')
            result_chars.append(decoded)
        except UnicodeDecodeError:
            # Can't decode as UTF-8 - keep original characters as-is
            result_chars.append(content[i:j])
        i = j
    else:
        # Character can't be encoded as CP1252 - keep as-is
        result_chars.append(content[i])
        i += 1

fixed = ''.join(result_chars)

with open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(fixed)

non_ascii = sum(1 for c in fixed if ord(c) > 127)
print(f'Done. Non-ASCII chars in fixed file: {non_ascii}')
