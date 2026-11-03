from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unexpected_runtime.prompt_library import PromptLibrary, PromptLibraryError


class PromptLibraryTests(unittest.TestCase):
    def test_packaged_catalog_covers_all_site_entries_and_categories(self):
        library = PromptLibrary.load()
        self.assertEqual(library.count, 1178)
        categories = library.list_categories()
        self.assertEqual(len(categories), 15)
        self.assertEqual(sum(item["count"] for item in categories), 1178)
        self.assertEqual(library.category_count("engineering"), 220)
        self.assertEqual(library.category_count("sales"), 110)

    def test_search_filters_by_text_and_category_and_pages_results(self):
        library = PromptLibrary.load()
        items, total = library.search(query="proposal", category="sales", limit=5, offset=0)
        self.assertGreaterEqual(total, 1)
        self.assertLessEqual(len(items), 5)
        self.assertTrue(all(item["category_id"] == "sales" for item in items))
        self.assertTrue(all("proposal" in item["title"].lower() for item in items))

        later, later_total = library.search(query="proposal", category="sales", limit=5, offset=5)
        self.assertEqual(later_total, total)
        self.assertTrue(set(item["id"] for item in items).isdisjoint(
            item["id"] for item in later
        ))

    def test_records_route_to_existing_canonical_roles(self):
        library = PromptLibrary.load()
        engineering = library.search(query="accessible dropdown", category="engineering")[0][0]
        sales = library.search(query="cold outreach email", category="sales")[0][0]
        self.assertEqual(engineering["agent_id"], "coding-engineer")
        self.assertEqual(sales["agent_id"], "sales-intel")
        self.assertEqual(len({item["agent_id"] for item in library.search(limit=200)[0]}), 15)

    def test_selected_prompt_produces_native_instructions_with_safety_boundaries(self):
        library = PromptLibrary.load()
        record = library.search(query="proposal", category="sales", limit=1)[0][0]
        instructions = library.render_instructions(library.get(record["id"]))
        self.assertIn(record["title"], instructions)
        self.assertIn("sales-intel", instructions)
        self.assertIn("draft only", instructions.lower())
        self.assertIn("approval", instructions.lower())
        self.assertIn("source", instructions.lower())

    def test_unknown_prompt_is_rejected(self):
        library = PromptLibrary.load()
        with self.assertRaises(PromptLibraryError):
            library.get("not-a-real-prompt")

    def test_duplicate_prompt_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = {
                "schema_version": 1,
                "catalog_id": "fixture",
                "source": {"name": "fixture", "url": "https://example.com"},
                "categories": [{"id": "sales", "name": "Sales", "count": 2, "agent_id": "sales-intel"}],
                "prompts": [
                    {"id": "sales-001", "title": "First", "category_id": "sales", "category": "Sales", "agent_id": "sales-intel"},
                    {"id": "sales-001", "title": "Duplicate", "category_id": "sales", "category": "Sales", "agent_id": "sales-intel"},
                ],
            }
            path = root / "prompt_catalog.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(PromptLibraryError):
                PromptLibrary.load(path, root)


if __name__ == "__main__":
    unittest.main()
