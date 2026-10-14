import sys
content = open('ui/templates/team_admin_onboarding.html', 'r', encoding='utf-8').read()
checks = [
    ('Has BOM', content[0] == '\ufeff'),
    ('Team Members emoji OK', '\U0001f464' in content),
    ('LLM robot emoji OK', '\U0001f916' in content),
    ('GitHub octopus emoji OK', '\U0001f419' in content),
    ('Delete trash emoji OK', '\U0001f5d1' in content),
    ('Verify plug emoji OK', '\U0001f50c' in content),
    ('Edit pencil emoji OK', '\u270f' in content),
    ('Save floppy emoji OK', '\U0001f4be' in content),
    ('Back arrow OK', '\u2190' in content),
    ('No garbled robot', '\u00f0\u0178\u00a4\u2013' not in content),
    ('No garbled plug', '\u00f0\u0178\u201c\u0152' not in content),
]
all_ok = True
for k, v in checks:
    status = 'PASS' if v else 'FAIL'
    if not v:
        all_ok = False
    sys.stdout.buffer.write(f'  {status}: {k}\n'.encode('utf-8'))
sys.stdout.buffer.write(f'\nOverall: {"ALL PASS" if all_ok else "SOME FAILURES"}\n'.encode('utf-8'))
