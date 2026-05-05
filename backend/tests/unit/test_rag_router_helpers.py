import json

import pytest
from fastapi import HTTPException

from routers.rag import _extract_text, _file_type_label


def test_file_type_label_valid_and_boundary_extensions():
    assert _file_type_label("report.pdf") == "pdf"
    assert _file_type_label("memo.docx") == "docx"
    assert _file_type_label("analysis.ipynb") == "ipynb"
    assert _file_type_label("unknown.csv") == "txt"


def test_extract_text_from_plain_text():
    assert _extract_text(b"hello report", "report.txt", "text/plain") == "hello report"


def test_extract_text_from_notebook():
    notebook = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Report\n"]},
            {"cell_type": "code", "source": ["print('x')"]},
        ]
    }

    result = _extract_text(json.dumps(notebook).encode(), "analysis.ipynb", "application/json")

    assert "[MARKDOWN]" in result
    assert "# Report" in result
    assert "[CODE]" in result


def test_extract_text_invalid_notebook_raises_422():
    with pytest.raises(HTTPException) as exc:
        _extract_text(b"{bad", "analysis.ipynb", "application/json")

    assert exc.value.status_code == 422
