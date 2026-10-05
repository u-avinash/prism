from types import SimpleNamespace

import utils.artifact_paths as artifact_paths


def test_managed_artifact_path_accepts_only_configured_root(monkeypatch, tmp_path):
    pdf_root = tmp_path / "pdfs"
    patch_root = tmp_path / "patches"
    pdf_root.mkdir()
    patch_root.mkdir()
    allowed = pdf_root / "incident.pdf"
    allowed.write_bytes(b"%PDF-test")
    outside = tmp_path / "unmanaged.pdf"
    outside.write_bytes(b"%PDF-private")

    monkeypatch.setattr(
        artifact_paths,
        "get_settings",
        lambda: SimpleNamespace(
            pdf_output_dir=str(pdf_root),
            patch_output_dir=str(patch_root),
        ),
    )

    assert artifact_paths.managed_artifact_path(str(allowed), "pdf") == allowed.resolve()
    assert artifact_paths.managed_artifact_path(str(outside), "pdf") is None


def test_managed_artifact_path_rejects_wrong_kind_suffix(monkeypatch, tmp_path):
    pdf_root = tmp_path / "pdfs"
    patch_root = tmp_path / "patches"
    pdf_root.mkdir()
    patch_root.mkdir()
    patch = patch_root / "fix.patch"
    patch.write_text("diff --git a/a b/a", encoding="utf-8")
    invalid_pdf = pdf_root / "report.txt"
    invalid_pdf.write_text("not a PDF", encoding="utf-8")

    monkeypatch.setattr(
        artifact_paths,
        "get_settings",
        lambda: SimpleNamespace(
            pdf_output_dir=str(pdf_root),
            patch_output_dir=str(patch_root),
        ),
    )

    assert artifact_paths.managed_artifact_path(str(patch), "patch") == patch.resolve()
    assert artifact_paths.managed_artifact_path(str(invalid_pdf), "pdf") is None
