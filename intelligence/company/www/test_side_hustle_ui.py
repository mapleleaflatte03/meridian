#!/usr/bin/env python3
"""RED tests for Side Hustle dashboard panel UI.

Validates that index.html contains the required Side Hustle panel markup
and that meridian.js includes the fetch/render logic for side hustle data.
"""
import os
import re
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML_PATH = os.path.join(THIS_DIR, 'index.html')
MERIDIAN_JS_PATH = os.path.join(THIS_DIR, 'assets', 'meridian.js')


class SideHustleDashboardUITest(unittest.TestCase):
    def setUp(self):
        with open(INDEX_HTML_PATH, 'r', encoding='utf-8') as f:
            self.index_html = f.read()
        with open(MERIDIAN_JS_PATH, 'r', encoding='utf-8') as f:
            self.meridian_js = f.read()

    def test_index_html_contains_side_hustle_panel_section(self):
        """Side Hustle panel section must exist in index.html."""
        self.assertIn('id="side-hustle-panel"', self.index_html)
        self.assertIn('Side Hustle', self.index_html)

    def test_index_html_contains_side_hustle_data_attributes(self):
        """Side Hustle panel must have data attributes for live updates."""
        required_attrs = [
            'data-side-hustle-panel',
            'data-hustle-active-count',
            'data-hustle-earnings-month',
            'data-hustle-success-rate',
            'data-hustle-latest-proof',
        ]
        for attr in required_attrs:
            self.assertIn(attr, self.index_html, f"Missing required attribute: {attr}")

    def test_index_html_labels_selector_as_directory_not_context_switch(self):
        """Institution selector copy must describe directory browsing only."""
        self.assertIn('Institution Directory', self.index_html)
        self.assertIn('id="institution-selector-note"', self.index_html)
        self.assertIn('Live status remains bound to the current workspace context.', self.index_html)

    def test_index_html_contains_start_hustle_button(self):
        """Run Side Hustle button must exist."""
        self.assertIn('data-start-demo-hustle', self.index_html)
        self.assertRegex(
            self.index_html,
            r'<button[^>]*data-start-demo-hustle[^>]*>.*Run Side Hustle.*</button>',
            "Run Side Hustle button not found or incorrectly formatted"
        )

    def test_meridian_js_has_side_hustle_panel_check(self):
        """meridian.js must check for side hustle panel presence."""
        self.assertIn('hasSideHustlePanel', self.meridian_js)
        self.assertRegex(
            self.meridian_js,
            r"hasSideHustlePanel\s*=\s*document\.querySelector\(['\"]?\[data-side-hustle-panel\]['\"]?\)",
            "hasSideHustlePanel check not found in meridian.js"
        )

    def test_meridian_js_has_render_side_hustle_panel_function(self):
        """meridian.js must define renderSideHustlePanel function."""
        self.assertIn('function renderSideHustlePanel', self.meridian_js)
        self.assertRegex(
            self.meridian_js,
            r'function renderSideHustlePanel\s*\(',
            "renderSideHustlePanel function not found"
        )

    def test_meridian_js_calls_render_side_hustle_panel_in_refresh(self):
        """refreshLivingInstitutionSurface must call renderSideHustlePanel."""
        self.assertIn('renderSideHustlePanel', self.meridian_js)
        # Check it's called in the refresh function
        refresh_match = re.search(
            r'function refreshLivingInstitutionSurface\s*\([^)]*\)\s*\{(.*?)\n\s*\}',
            self.meridian_js,
            re.DOTALL
        )
        self.assertIsNotNone(refresh_match, "refreshLivingInstitutionSurface function not found")
        refresh_body = refresh_match.group(1)
        self.assertIn('renderSideHustlePanel', refresh_body)

    def test_meridian_js_status_copy_declares_workspace_bound_contract(self):
        """Status copy must state workspace-bound runtime context contract."""
        self.assertIn(
            "Institution status updated ' + new Date().toLocaleString() + '. Runtime context remains workspace-bound.",
            self.meridian_js,
        )
        self.assertIn(
            "Institution directory selection updated ' + new Date().toLocaleString() + '. Live status remains workspace-bound.",
            self.meridian_js,
        )

    def test_meridian_js_has_start_hustle_handler(self):
        """meridian.js must wire up Run Side Hustle button click handler."""
        self.assertIn('data-start-demo-hustle', self.meridian_js)
        self.assertRegex(
            self.meridian_js,
            r"querySelector\(['\"]?\[data-start-demo-hustle\]['\"]?\)",
            "Start demo hustle button handler not found"
        )

    def test_meridian_js_posts_to_api_agent_hustle(self):
        """Side hustle handler must POST to /api/agent/hustle."""
        self.assertIn('/api/agent/hustle', self.meridian_js)
        # Check for fetch POST pattern
        self.assertRegex(
            self.meridian_js,
            r"fetch\(['\"]?/api/agent/hustle['\"]?.*method:\s*['\"]POST['\"]",
            "POST to /api/agent/hustle not found in meridian.js"
        )


if __name__ == '__main__':
    unittest.main()
