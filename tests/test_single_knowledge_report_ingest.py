import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.ingest_one_knowledge_report import build_body, select_knowledge_unit


class SingleKnowledgeReportIngestTests(unittest.TestCase):
    def test_section_selection_includes_nested_content_and_stops_at_peer(self):
        text = """# **Stateful Memory Report**

## Memory taxonomy

Typed memory matters.

### Procedural memory

Policies use exact lookup.

## Retrieval

Retrieval is separately classified.
"""
        selected, unit = select_knowledge_unit(text, Path("Stateful Memory Report.md"), "Memory taxonomy")

        self.assertIn("### Procedural memory", selected)
        self.assertNotIn("## Retrieval", selected)
        self.assertEqual("report_section", unit["kind"])
        self.assertEqual("Stateful Memory Report", unit["reportTitle"])
        self.assertEqual("Memory taxonomy", unit["sectionHeading"])
        self.assertEqual(2, unit["sectionLevel"])

    def test_sections_share_source_identity_but_have_distinct_page_identity(self):
        text = """# **Stateful Memory Report**

## Memory taxonomy

Typed memory matters.

## Retrieval

Retrieval is separately classified.
"""
        source_path = Path("Stateful Memory Report.md")
        context = {"workspaceId": "workspace-one", "companyId": "company-one"}

        def body_for(heading):
            selected, unit = select_knowledge_unit(text, source_path, heading)
            args = SimpleNamespace(
                title="",
                source_uri="",
                route_or_path="",
                scope="project",
                category="agent-memory",
                description="Reviewed architecture knowledge.",
                keyword=["agent memory", "retrieval"],
                taxonomy_path=[["AI infrastructure", "agent memory"]],
                document_type="",
                knowledge_status="current",
                authority_level="reviewed",
                status_reason="",
                superseded_by_document_id="",
                source_type="reviewed_markdown_report",
                source_report_route="/knowledge/project/research/stateful-memory-report",
                classification_note="Reviewed independently.",
                tag=[],
                project_id="project-memoryendpoints-com",
                project_label="MemoryEndpoints.com",
            )
            return build_body(args, context, "MemoryEndpoints-Backend-Agent", source_path, text, selected, unit)

        taxonomy = body_for("Memory taxonomy")
        retrieval = body_for("Retrieval")

        self.assertEqual(taxonomy["sourceUri"], retrieval["sourceUri"])
        self.assertNotEqual(taxonomy["routeOrPath"], retrieval["routeOrPath"])
        self.assertEqual(taxonomy["metadata"]["sourceContentHash"], retrieval["metadata"]["sourceContentHash"])
        self.assertNotEqual(taxonomy["metadata"]["knowledgeUnitContentHash"], retrieval["metadata"]["knowledgeUnitContentHash"])
        self.assertEqual("reviewed-report-section", taxonomy["documentType"])
        self.assertEqual("Memory taxonomy", taxonomy["title"])
        self.assertEqual("current", taxonomy["knowledgeStatus"])
        self.assertEqual("reviewed", taxonomy["authorityLevel"])

    def test_missing_section_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "section heading not found"):
            select_knowledge_unit("# Report\n\n## Present\n", Path("report.md"), "Absent")

    def test_section_selection_matches_rendered_markdown_escaped_punctuation(self):
        text = r"""# Report

### **1\. Proposed LLMWikis.org Page Map**

The historical route proposal.

### **W3C Content Negotiation (RFC 7231\)**

The historical protocol proposal.
"""

        selected, unit = select_knowledge_unit(
            text,
            Path("report.md"),
            "1. Proposed LLMWikis.org Page Map",
        )
        protocol, protocol_unit = select_knowledge_unit(
            text,
            Path("report.md"),
            "W3C Content Negotiation (RFC 7231)",
        )

        self.assertIn("historical route proposal", selected)
        self.assertEqual("1. Proposed LLMWikis.org Page Map", unit["sectionHeading"])
        self.assertIn("historical protocol proposal", protocol)
        self.assertEqual("W3C Content Negotiation (RFC 7231)", protocol_unit["sectionHeading"])

    def test_stop_heading_excludes_nested_appendix(self):
        text = """# Report

## Synthesis

The durable conclusion.

#### Works cited

1. A reference that remains on the source page.
"""
        selected, unit = select_knowledge_unit(text, Path("report.md"), "Synthesis", "Works cited")

        self.assertIn("The durable conclusion.", selected)
        self.assertNotIn("Works cited", selected)
        self.assertEqual("Works cited", unit["stopHeading"])
        self.assertEqual(5, unit["lineEnd"])


if __name__ == "__main__":
    unittest.main()
