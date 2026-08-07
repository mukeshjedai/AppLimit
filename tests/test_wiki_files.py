from applimit.wiki_files import (
    build_attachment_record,
    build_file_markdown_link,
    page_attachments,
    validate_upload_filename,
)


def test_validate_upload_filename_allows_pdf() -> None:
    assert validate_upload_filename("report.pdf") == "report.pdf"


def test_validate_upload_filename_blocks_exe() -> None:
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        validate_upload_filename("virus.exe")


def test_build_file_markdown_link() -> None:
    md = build_file_markdown_link("notes.pdf", "/api/wiki/files/abc.pdf")
    assert md == "[notes.pdf](/api/wiki/files/abc.pdf)"


def test_page_attachments_from_page_json() -> None:
    page = {
        "attachments": [
            build_attachment_record(
                file_id="abc123.pdf",
                original_name="notes.pdf",
                size=42,
                content_type="application/pdf",
                uploaded_at="2026-01-01T00:00:00Z",
            )
        ]
    }
    items = page_attachments(page)
    assert len(items) == 1
    assert items[0]["filename"] == "notes.pdf"
