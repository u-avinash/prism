"""
╔══════════════════════════════════════════════════════════════════════╗
║                          P  R  I  S  M                               ║
║       Autonomous AI Incident Management System                       ║
╚══════════════════════════════════════════════════════════════════════╝

  Building an Autonomous AI Incident Management System
  with LangGraph and OpenTelemetry

  Author   : Upadhyayula Avinash
  GitHub   : https://github.com/u-avinash
  LinkedIn : https://www.linkedin.com/in/avinash-upadhyayula/
  Email    : uavinash.csit@gmail.com

  Copyright (c) 2026-2035 Upadhyayula Avinash. All rights reserved.
"""
"""
Test patch file format validation.

Ensures that generated patch files have proper formatting for Anypoint Studio,
git apply, and standard patch tools.
"""
import sys
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.nodes.patch_generator import (
    _apply_targeted_fix,
    _validate_patch_format,
    generate_patch_file_node,
)
from config.settings import get_settings


def test_valid_patch_format():
    """Test that a properly formatted patch passes validation."""
    valid_patch = """--- a/src/main/mule/test.xml
+++ b/src/main/mule/test.xml
@@ -1,5 +1,6 @@
 <mule>
-    <flow name="test">
+    <!-- Fixed flow -->
+    <flow name="test-fixed">
         <logger message="test"/>
     </flow>
 </mule>
"""
    assert _validate_patch_format(valid_patch), "Valid patch should pass validation"
    print("[PASS] Valid patch format test passed")


def test_invalid_patch_concatenated_headers():
    """Test that a patch with concatenated headers fails validation."""
    invalid_patch = """--- a/src/main/mule/test.xml+++ b/src/main/mule/test.xml
@@ -1,5 +1,6 @@
 <mule>
-    <flow name="test">
+    <flow name="test-fixed">
         <logger message="test"/>
     </flow>
 </mule>
"""
    assert not _validate_patch_format(invalid_patch), "Invalid patch with concatenated headers should fail validation"
    print("[PASS] Invalid concatenated headers test passed")


def test_empty_patch():
    """Test that an empty patch fails validation."""
    assert not _validate_patch_format(""), "Empty patch should fail validation"
    assert not _validate_patch_format(None), "None patch should fail validation"
    print("[PASS] Empty patch test passed")


def test_patch_with_no_diff_markers():
    """Test that a patch without diff markers fails validation."""
    no_markers = """This is just some text
without any patch markers
at all
"""
    assert not _validate_patch_format(no_markers), "Patch without diff markers should fail validation"
    print("[PASS] No diff markers test passed")


def test_real_world_mule_patch():
    """Test a real-world MuleSoft patch format."""
    real_patch = """--- a/src/main/mule/order-validation.xml
+++ b/src/main/mule/order-validation.xml
@@ -33,12 +33,16 @@
                             <ee:set-variable variableName="errorResults"><![CDATA[%dw 2.0
 output application/json
 ---
-vars.errorResults ++ [{
+/* 
+ * Fix: guard against vars.errorResults being null/uninitialized in the error path.
+ * This prevents the error handler from failing while appending the current error result.
+ */
+(vars.errorResults default []) ++ [{
     scenario_id: 2,
     scenario_name: "HTTP Connectivity Error",
-    error_type: vars.errorType,
-    error_message: vars.errorMessage,
-    severity: vars.errorSeverity,
+    error_type: vars.errorType default "UNKNOWN",
+    error_message: vars.errorMessage default "Unhandled error occurred",
+    severity: vars.errorSeverity default "ERROR",
     timestamp: now() as String
 }]]]></ee:set-variable>
                         </ee:variables>
"""
    assert _validate_patch_format(real_patch), "Real-world MuleSoft patch should pass validation"
    print("[PASS] Real-world MuleSoft patch test passed")


def test_patch_generator_accepts_hyphenated_fence_label():
    """The generator and UI must accept realistic labels such as ``mule-xml``."""
    original = "<flow name=\"orders\">\n    <logger message=\"old\"/>\n</flow>\n"
    proposed_fix = """**Original Code**
```mule-xml
<flow name="orders">
    <logger message="old"/>
</flow>
```

**Fixed Code**
```mule-xml
<flow name="orders">
    <logger message="new"/>
</flow>
```"""

    fixed = _apply_targeted_fix(original, proposed_fix, {"incident_id": "TEST"})
    assert fixed is not None
    assert 'message="new"' in fixed
    print("[PASS] Hyphenated fenced-code label test passed")


def test_generated_patch_contains_only_unified_diff():
    """Generated artifacts must remain directly consumable by ``git apply``."""
    original_output_dir = get_settings().patch_output_dir
    original = "first line\nsecond line\n"
    proposed_fix = """**Original Code**
```text
first line
second line
```

**Fixed Code**
```text
first line
updated line
```"""

    with tempfile.TemporaryDirectory() as temp_dir:
        get_settings().patch_output_dir = temp_dir
        state = {
            "incident_id": "TST1",
            "proposed_fix": proposed_fix,
            "original_code": original,
            "error_file_path": "sample.txt",
            "fix_explanation": "Update the sample.",
            "messages": [],
        }
        result = generate_patch_file_node(state)
        patch_path = Path(result["patch_path"])
        patch_content = patch_path.read_text(encoding="utf-8")

        assert patch_content.startswith("--- sample.txt\n+++ sample.txt\n")
        assert "# Patch Information" not in patch_content
        assert "Update the sample." not in patch_content
        assert _validate_patch_format(patch_content)

    get_settings().patch_output_dir = original_output_dir
    print("[PASS] Pure unified-diff patch generation test passed")


def test_patch_with_metadata():
    """Test that a patch with metadata section is still valid."""
    patch_with_metadata = """--- a/src/main/mule/test.xml
+++ b/src/main/mule/test.xml
@@ -1,5 +1,6 @@
 <mule>
-    <flow name="test">
+    <flow name="test-fixed">
         <logger message="test"/>
     </flow>
 </mule>

# ============================================================================
# Patch Information
# ============================================================================
# Incident ID: TEST123
# Application: test-service
# Generated: 2026-04-20T15:17:19
"""
    assert _validate_patch_format(patch_with_metadata), "Patch with metadata should pass validation"
    print("[PASS] Patch with metadata test passed")


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("Running Patch Format Validation Tests")
    print("="*60 + "\n")
    
    try:
        test_valid_patch_format()
        test_invalid_patch_concatenated_headers()
        test_empty_patch()
        test_patch_with_no_diff_markers()
        test_real_world_mule_patch()
        test_patch_generator_accepts_hyphenated_fence_label()
        test_generated_patch_contains_only_unified_diff()
        test_patch_with_metadata()
        
        print("\n" + "="*60)
        print("[SUCCESS] All tests passed successfully!")
        print("="*60 + "\n")
        return 0
        
    except AssertionError as e:
        print("\n" + "="*60)
        print(f"[FAIL] Test failed: {e}")
        print("="*60 + "\n")
        return 1
    except Exception as e:
        print("\n" + "="*60)
        print(f"[ERROR] Unexpected error: {e}")
        print("="*60 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
