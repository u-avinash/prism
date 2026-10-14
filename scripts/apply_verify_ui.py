#!/usr/bin/env python3
"""Re-apply verification UI improvements to team_admin_onboarding.html"""
import sys

path = 'ui/templates/team_admin_onboarding.html'
content = open(path, 'r', encoding='utf-8').read()
original_len = len(content)

# ── Change 1: Update setVerifyState ──────────────────────────────────────────
old1 = (
    "function setVerifyState(type, ok, message) {\n"
    "  verificationState[type] = ok;\n"
    "  var el = document.getElementById('verifyState-' + type);\n"
    "  if (el) {\n"
    "    el.textContent = 'Status: ' + message;\n"
    "    el.classList.toggle('table-primary', ok);\n"
    "  }\n"
    "  setIntegrationButtons(type, ok);\n"
    "}"
)
new1 = (
    "function setVerifyState(type, ok, message) {\n"
    "  verificationState[type] = ok;\n"
    "  var el = document.getElementById('verifyState-' + type);\n"
    "  if (el) {\n"
    "    var badge = ok ? '[\u2713 OK]' : '[\u2717 FAIL]';\n"
    "    el.textContent = badge + ' ' + message;\n"
    "    el.className = 'integration-verification-note ' + (ok ? 'verify-state-ok' : 'verify-state-fail');\n"
    "  }\n"
    "  setIntegrationButtons(type, ok);\n"
    "}"
)
if old1 in content:
    content = content.replace(old1, new1, 1)
    print("Change 1 (setVerifyState): APPLIED")
else:
    print("Change 1 (setVerifyState): NOT FOUND — skipped")

# ── Change 2: Update testIntegration success/error blocks ────────────────────
old2 = (
    "    if (r.ok && d.success && d.verification_token) {\n"
    "      verificationReceipt[type] = d.verification_token;\n"
    "      setVerifyState(type, true, d.message || 'Verified successfully');\n"
    "      alert(d.message || 'Verification successful');\n"
    "    } else {\n"
    "      verificationReceipt[type] = '';\n"
    "      setVerifyState(type, false, d.error || 'Verification did not produce a save receipt.');\n"
    "      alert(d.error || 'Verification failed');\n"
    "    }\n"
    "  } catch (e) {\n"
    "    setVerifyState(type, false, e.message);\n"
    "    alert('Network error: ' + e.message);\n"
    "  }\n"
    "}"
)
new2 = (
    "    if (r.ok && d.success && d.verification_token) {\n"
    "      verificationReceipt[type] = d.verification_token;\n"
    "      var msg = d.message || 'Verified successfully';\n"
    "      if (type === 'llm' && d.prism_validation) {\n"
    "        var pv = d.prism_validation;\n"
    "        msg += '\\n\\nPRISM Validation: ' + (pv.ok ? '[\u2713 OK]' : '[\u2717 FAIL]') + '\\n' + (pv.detail || '');\n"
    "      }\n"
    "      setVerifyState(type, true, msg);\n"
    "    } else {\n"
    "      verificationReceipt[type] = '';\n"
    "      var errMsg = d.error || 'Verification did not produce a save receipt.';\n"
    "      if (type === 'llm' && d.prism_validation) {\n"
    "        var pv2 = d.prism_validation;\n"
    "        errMsg += '\\n\\nPRISM Validation: ' + (pv2.ok ? '[\u2713 OK]' : '[\u2717 FAIL]') + '\\n' + (pv2.detail || '');\n"
    "      }\n"
    "      setVerifyState(type, false, errMsg);\n"
    "    }\n"
    "  } catch (e) {\n"
    "    setVerifyState(type, false, 'Network error: ' + e.message);\n"
    "  }\n"
    "}"
)
if old2 in content:
    content = content.replace(old2, new2, 1)
    print("Change 2 (testIntegration): APPLIED")
else:
    print("Change 2 (testIntegration): NOT FOUND — skipped")

# ── Write back ────────────────────────────────────────────────────────────────
if len(content) != original_len:
    open(path, 'w', encoding='utf-8').write(content)
    print(f"File written ({original_len} -> {len(content)} chars)")
else:
    print("No net change in file length (no writes or changes cancelled out)")

# ── Verify no BOM ─────────────────────────────────────────────────────────────
raw = open(path, 'rb').read(4)
if raw[:3] == b'\xef\xbb\xbf':
    print("WARNING: BOM detected — stripping")
    full = open(path, 'rb').read()
    open(path, 'wb').write(full[3:])
else:
    print("BOM check: OK (no BOM)")
