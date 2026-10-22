"""Office schemas sent to providers must expose array items to local templates."""
import json

import pytest

from workbench.engine import TEAM_TOOLS
from workbench.harness import ToolExecutor
from workbench.providers import _request_payload, _tools
from workbench.webtools import WebTools


@pytest.fixture
def office_schemas():
    return {tool["name"]: tool["parameters"] for tool in ToolExecutor(None).schemas()}


def assert_explicit_array_items(value):
    if isinstance(value, dict):
        if value.get("type") == "array":
            # Missing items can resolve to dict.items in a local Jinja template.
            assert isinstance(value.get("items"), dict) and value["items"].get("type")
        for child in value.values():
            assert_explicit_array_items(child)
    elif isinstance(value, list):
        for child in value:
            assert_explicit_array_items(child)


@pytest.mark.parametrize("kind", ["local", "openai", "anthropic"])
def test_provider_payloads_keep_explicit_items_for_every_nested_array(kind):
    definitions = ToolExecutor(None).schemas() + TEAM_TOOLS + WebTools({"search": {"enabled": True}}).schemas()
    payload = _request_payload(kind, "test-model", {}, [{"role": "user", "content": "test"}],
                               _tools(definitions), "policy", 128)
    sent = json.loads(json.dumps(payload))["tools"]
    if kind == "local":
        sent_schemas = {tool["function"]["name"]: tool["function"]["parameters"] for tool in sent}
    elif kind == "anthropic":
        sent_schemas = {tool["name"]: tool["input_schema"] for tool in sent}
    else:
        sent_schemas = {tool["name"]: tool["parameters"] for tool in sent}
    assert sent_schemas == {tool["name"]: tool["parameters"] for tool in definitions}
    assert_explicit_array_items(sent_schemas)


def test_docx_tables_and_each_operation_keep_the_existing_minimal_shape(office_schemas):
    write = office_schemas["docx_write"]
    assert set(write["required"]) == {"path", "expected_sha256"}
    tables = write["properties"]["tables"]
    rows = tables["items"]
    assert rows["type"] == rows["items"]["type"] == "array"
    assert rows["items"]["items"] == {"type": "string"}
    assert "minItems" not in tables
    operation = office_schemas["docx_edit"]["properties"]["operations"]["items"]
    assert operation["type"] == "object"
    fields_by_type = {
        "append_paragraph": {"type", "text"},
        "replace_paragraph": {"type", "index", "text"},
        "replace_cell": {"type", "table", "row", "column", "text"},
        "append_table": {"type", "rows"},
    }
    assert set(operation["properties"]["type"]["enum"]) == set(fields_by_type)
    for fields in fields_by_type.values():
        assert set(operation["required"]) <= fields <= set(operation["properties"])
    assert operation["properties"]["rows"] == rows
    assert operation["properties"]["text"] == {"type": "string"}
    for name in ("index", "table", "row", "column"):
        assert operation["properties"][name]["type"] == "integer"


def test_xlsx_cell_schema_keeps_all_json_scalar_types_including_null(office_schemas):
    cells = office_schemas["xlsx_write"]["properties"]["cells"]
    cell = cells["items"]
    assert cell["type"] == "object"
    assert set(cell["required"]) == set(cell["properties"]) == {"sheet", "cell", "value"}
    assert cell["properties"]["sheet"]["type"] == cell["properties"]["cell"]["type"] == "string"
    # JSON Schema number includes integer; null is needed to clear a cell.
    assert set(cell["properties"]["value"]["type"]) == {"string", "number", "boolean", "null"}
    assert "minItems" not in cells


def test_pptx_schemas_describe_slide_body_and_integer_edit_targets(office_schemas):
    slide = office_schemas["pptx_write"]["properties"]["slides"]["items"]
    assert slide["type"] == "object"
    assert set(slide["required"]) == set(slide["properties"]) == {"title", "body"}
    assert slide["properties"]["title"] == {"type": "string"}
    assert slide["properties"]["body"] == {"type": "array", "items": {"type": "string"}}
    operation = office_schemas["pptx_edit"]["properties"]["operations"]["items"]
    assert operation["type"] == "object"
    assert set(operation["required"]) == set(operation["properties"]) == {"slide", "shape", "paragraph", "text"}
    assert operation["properties"]["text"] == {"type": "string"}
    for name in ("slide", "shape", "paragraph"):
        assert operation["properties"][name]["type"] == "integer"
