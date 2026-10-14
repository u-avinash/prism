"""
Repair script for incident NTTD0WVL:
1. Fixes repo_full_name (adds missing owner prefix)
2. Rebuilds proposed_fix with proper Original Code + Fixed Code blocks
3. Regenerates the patch file from the correct diff
"""
import sys
import difflib
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '.')

from storage.database import get_session
from storage.incident_repository import IncidentRepository
from agents.nodes.patch_generator import generate_patch_file_node
from agents.state import AgentState

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

INCIDENT_ID = 'NTTD0WVL'

# ── The ORIGINAL (buggy) DataWeave code, inferred from the error message ──────
# The exception.message in the incident metadata contains the exact buggy DWL
# expression. The Mule XML wrapping is reconstructed from the error context.
ORIGINAL_CODE_BLOCK = '''\
        <ee:transform doc:name="Enrich Order" doc:id="transform-enrich-order">
            <ee:message>
                <ee:set-payload><![CDATA[%dw 2.0
output application/json
var order = payload
---
{
  orderId: order.orderId default "N/A",
  // Bug: customer object doesn't exist in input, causing null pointer error
  customerId: order.customer.id,
  customerEmail: order.customer.email,
  items: order.items default []
}]]></ee:set-payload>
            </ee:message>
        </ee:transform>'''

# ── The FIXED version (safe navigation + defaults) ────────────────────────────
FIXED_CODE_BLOCK = '''\
        <ee:transform doc:name="Enrich Order" doc:id="transform-enrich-order">
            <ee:message>
                <ee:set-payload><![CDATA[%dw 2.0
output application/json
var order = payload
---
{
  orderId: order.orderId default "N/A",
  // Safe navigation with defaults for missing customer object
  customerId: order.customer?.id default "UNKNOWN",
  customerEmail: order.customer?.email default "unknown@example.com",
  items: order.items default []
}]]></ee:set-payload>
            </ee:message>
        </ee:transform>'''

# ── Build the full proposed_fix in the standard two-block format ───────────────
PROPOSED_FIX = f"""**Original Code (with context):**
```mule_xml
{ORIGINAL_CODE_BLOCK}
```

**Fixed Code (with same context):**
```mule_xml
{FIXED_CODE_BLOCK}
```

## Explanation
The DataWeave transformation inside the `enrich-order` sub-flow was accessing
`order.customer.id` and `order.customer.email` using direct (unsafe) field
selectors. When the incoming payload does not contain a `customer` object —
which is valid for guest or anonymous orders — the DataWeave engine throws a
`NullPointerException` because it cannot navigate into a null value.

The fix applies the **safe-navigation operator (`?.`)** for both customer
fields and adds **`default` values** so the transformation succeeds regardless
of whether the customer object is present:

- `order.customer?.id default "UNKNOWN"` — returns `"UNKNOWN"` when customer
  is absent instead of throwing an exception.
- `order.customer?.email default "unknown@example.com"` — returns a safe
  sentinel email so downstream processing does not receive a null value.

This change is backward-compatible: when the customer object is present, the
existing values are used as before.
"""


def repair():
    logger.info(f"Repairing incident {INCIDENT_ID}")

    with get_session() as session:
        repo = IncidentRepository(session)
        inc = repo.get_by_id(INCIDENT_ID)
        if not inc:
            logger.error(f"Incident {INCIDENT_ID} not found")
            return

        # ── 1. Fix repo_full_name if it is missing the owner prefix ───────────
        current_repo = inc.repo_full_name or ''
        metadata = getattr(inc, 'incident_metadata', {}) or {}
        custom_attrs = metadata.get('custom_attributes', {}) or {}
        github_org = custom_attrs.get('github.org', '')
        github_repo_name = custom_attrs.get('github.repo', '')
        correct_repo = (
            f"{github_org}/{github_repo_name}"
            if github_org and github_repo_name
            else current_repo
        )

        if current_repo != correct_repo and correct_repo:
            logger.info(f"Fixing repo_full_name: '{current_repo}' → '{correct_repo}'")
        else:
            correct_repo = current_repo
            logger.info(f"repo_full_name looks correct: {correct_repo}")

        # ── 2. Update proposed_fix and repo_full_name in DB ───────────────────
        repo.update(
            INCIDENT_ID,
            repo_full_name=correct_repo,
            proposed_fix=PROPOSED_FIX,
            fix_explanation=(
                "The DataWeave transformation was accessing customer fields "
                "without safe navigation (`?.`). Added safe navigation operators "
                "and default values to prevent NullPointerException when the "
                "customer object is absent from the payload."
            ),
        )
        logger.info("✓ Updated proposed_fix and repo_full_name in DB")

    # ── 3. Regenerate the patch file ──────────────────────────────────────────
    with get_session() as session:
        repo = IncidentRepository(session)
        inc = repo.get_by_id(INCIDENT_ID)

        state: AgentState = {
            'incident_id': INCIDENT_ID,
            'app_name': inc.app_name,
            'environment': inc.environment,
            'error_title': inc.error_title,
            'error_description': inc.error_description,
            'stack_trace': inc.stack_trace,
            'severity': inc.severity,
            'rca_text': inc.rca_text,
            'repo_full_name': inc.repo_full_name,
            'error_file_path': inc.error_file_path,
            'error_line_number': inc.error_line_number,
            'error_file_type': inc.error_file_type or 'mule_xml',
            'proposed_fix': PROPOSED_FIX,
            # original_code is not available (GitHub fetch failed at the time),
            # but the patch generator can diff the two code blocks directly.
            'original_code': None,
            'workflow_completed_steps': list(inc.workflow_completed_steps or []),
            'workflow_progress_pct': inc.workflow_progress_pct or 0.0,
            'messages': [],
            'project_id': getattr(inc, 'project_id', None),
        }

    logger.info("Regenerating patch from fixed proposed_fix ...")
    state = generate_patch_file_node(state)

    if state.get('patch_path'):
        patch_path = state['patch_path']
        logger.info(f"✓ Patch regenerated: {patch_path}")
        with open(patch_path, 'r', encoding='utf-8') as f:
            patch_content = f.read()

        lines_deleted = sum(
            1 for l in patch_content.splitlines()
            if l.startswith('-') and not l.startswith('---')
        )
        lines_added = sum(
            1 for l in patch_content.splitlines()
            if l.startswith('+') and not l.startswith('+++')
        )

        print("\n" + "=" * 60)
        print("PATCH ANALYSIS")
        print("=" * 60)
        print(f"Lines removed : {lines_deleted}")
        print(f"Lines added   : {lines_added}")
        print()
        print("PATCH CONTENT:")
        print("-" * 60)
        print(patch_content)
        print("-" * 60)
    else:
        logger.error("✗ Patch generation failed")

    print("\nMessages:", state.get('messages', []))


if __name__ == '__main__':
    repair()
