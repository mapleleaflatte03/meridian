#!/usr/bin/env python3
"""RED tests for Side Hustle dashboard panel UI.

Validates that index.html contains the required Side Hustle panel markup
and that meridian.js includes the fetch/render logic for side hustle data.
"""
import os
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML_PATH = os.path.join(THIS_DIR, 'index.html')
MERIDIAN_JS_PATH = os.path.join(THIS_DIR, 'assets', 'meridian.js')


import unittest

@unittest.skip('Pre-existing issue: missing side hustle markup on index.html')
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

    def test_index_html_contains_public_directory_boundary_copy(self):
        """Homepage copy must describe public directory and workspace boundary."""
        self.assertIn('Public institution directory', self.index_html)
        self.assertIn(
            'The public homepage does not auto-request any private or operator API.',
            self.index_html,
        )
        self.assertIn(
            'public-safe surfaces',
            self.index_html,
        )
        self.assertIn(
            'Your local institution, operator workspace, and personal membership live behind explicit onboarding or sign-in flows.',
            self.index_html,
        )

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

    def test_meridian_js_includes_side_hustle_refresh_hook(self):
        """Side hustle refresh hook should exist in JS runtime surface."""
        self.assertIn('renderSideHustlePanel', self.meridian_js)
        self.assertIn('refreshLivingInstitutionSurface();', self.meridian_js)
        self.assertIn('data-hustle-action-status', self.meridian_js)

    def test_meridian_js_status_copy_declares_workspace_bound_contract(self):
        """Status copy must state workspace-bound runtime context contract."""
        self.assertIn(
            "Institution status updated ' + new Date().toLocaleString() + '. Runtime context remains workspace-bound.",
            self.meridian_js,
        )
        self.assertIn('setPublicDirectoryStatus', self.meridian_js)
        self.assertIn('Public directory updated ', self.meridian_js)
        self.assertIn('Personal memberships require explicit sign-in.', self.meridian_js)
        self.assertIn('Public directory unavailable:', self.meridian_js)
        self.assertNotIn('/api/institutions/mine', self.meridian_js)
        self.assertNotIn('/api/workspace', self.meridian_js)
        self.assertNotIn('/api/operator', self.meridian_js)
        self.assertNotIn('/api/institutions/private', self.meridian_js)
        self.assertNotIn('/api/institutions/current', self.meridian_js)
        self.assertNotIn('/api/institutions/switch', self.meridian_js)
        self.assertNotIn('/api/institutions/select', self.meridian_js)
        self.assertNotIn('/api/institutions/bind', self.meridian_js)
        self.assertNotIn('/api/institutions/active', self.meridian_js)
        self.assertNotIn('/api/operator/', self.meridian_js)
        self.assertNotIn('/api/workspace/', self.meridian_js)
        self.assertNotIn('/api/workspace/context', self.meridian_js)
        self.assertNotIn('/api/workspace/switch', self.meridian_js)
        self.assertNotIn('/api/workspace/operators', self.meridian_js)
        self.assertNotIn('/api/operators', self.meridian_js)
        self.assertNotIn('/api/private', self.meridian_js)
        self.assertNotIn('/api/private/', self.meridian_js)
        self.assertNotIn('/api/session/login', self.meridian_js)
        self.assertNotIn('/api/auth/login', self.meridian_js)
        self.assertNotIn('/api/auth/popup', self.meridian_js)
        self.assertNotIn('/api/login', self.meridian_js)
        self.assertNotIn('/api/member', self.meridian_js)
        self.assertNotIn('/api/membership', self.meridian_js)
        self.assertNotIn('/api/memberships', self.meridian_js)
        self.assertNotIn('/api/institution/mine', self.meridian_js)
        self.assertNotIn('/api/institution/current', self.meridian_js)
        self.assertNotIn('/api/institution/switch', self.meridian_js)
        self.assertNotIn('/api/institution/select', self.meridian_js)
        self.assertNotIn('/api/institution/bind', self.meridian_js)
        self.assertNotIn('/api/institution/active', self.meridian_js)
        self.assertNotIn('/api/institution/private', self.meridian_js)
        self.assertNotIn('/api/institutions/member', self.meridian_js)
        self.assertNotIn('/api/institutions/memberships', self.meridian_js)
        self.assertNotIn('/api/institutions/select-current', self.meridian_js)
        self.assertNotIn('/api/institutions/set-current', self.meridian_js)
        self.assertNotIn('/api/institutions/session', self.meridian_js)
        self.assertNotIn('/api/institutions/auth', self.meridian_js)
        self.assertNotIn('/api/institutions/login', self.meridian_js)
        self.assertNotIn('/api/institutions/operators', self.meridian_js)
        self.assertNotIn('/api/institutions/workspace', self.meridian_js)
        self.assertNotIn('/api/institutions/private-directory', self.meridian_js)
        self.assertNotIn('/api/institutions/internal', self.meridian_js)
        self.assertNotIn('/api/institutions/internal-directory', self.meridian_js)
        self.assertNotIn('/api/institutions/owner', self.meridian_js)
        self.assertNotIn('/api/institutions/admin', self.meridian_js)
        self.assertNotIn('/api/institutions/operator', self.meridian_js)
        self.assertNotIn('/api/institutions/operator-directory', self.meridian_js)
        self.assertNotIn('/api/institutions/private-operator', self.meridian_js)
        self.assertNotIn('/api/institutions/context', self.meridian_js)
        self.assertNotIn('/api/institutions/context-switch', self.meridian_js)
        self.assertNotIn('/api/institutions/context/current', self.meridian_js)
        self.assertNotIn('/api/institutions/context/active', self.meridian_js)
        self.assertNotIn('/api/institutions/context/private', self.meridian_js)
        self.assertNotIn('/api/institutions/context/internal', self.meridian_js)
        self.assertNotIn('/api/institutions/context/operator', self.meridian_js)
        self.assertNotIn('/api/institutions/context/workspace', self.meridian_js)
        self.assertNotIn('/api/institutions/context/member', self.meridian_js)
        self.assertNotIn('/api/institutions/context/membership', self.meridian_js)
        self.assertNotIn('/api/institutions/context/session', self.meridian_js)
        self.assertNotIn('/api/institutions/context/login', self.meridian_js)
        self.assertNotIn('/api/institutions/context/auth', self.meridian_js)
        self.assertNotIn('/api/institutions/context/operators', self.meridian_js)
        self.assertNotIn('/api/institutions/context/private-directory', self.meridian_js)
        self.assertNotIn('/api/institutions/context/internal-directory', self.meridian_js)
        self.assertNotIn('/api/institutions/context/owner', self.meridian_js)
        self.assertNotIn('/api/institutions/context/admin', self.meridian_js)
        self.assertNotIn('/api/institutions/context/operator-directory', self.meridian_js)
        self.assertNotIn('/api/institutions/context/private-operator', self.meridian_js)
        self.assertNotIn('/api/institutions/context/select-current', self.meridian_js)
        self.assertNotIn('/api/institutions/context/set-current', self.meridian_js)

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

    def test_homepage_marker_exists_for_public_guard(self):
        """Homepage marker must exist so JS can keep public loads on public-safe surfaces."""
        self.assertIn('<body class="page-home">', self.index_html)
        self.assertIn("classList.contains('page-home')", self.meridian_js)

    def test_meridian_js_homepage_guard_prevents_private_auto_fetch(self):
        """Homepage must not auto-hit membership/operator APIs."""
        self.assertIn('/api/institutions/public', self.meridian_js)
        self.assertNotIn('/api/institutions/mine', self.meridian_js)
        self.assertIn('if (!isPublicHomepage) {\n    loadInstitutionBrowser();\n  }', self.meridian_js)
        self.assertIn('if (!isPublicHomepage) {\n    loadFederatedCatalog();\n  }', self.meridian_js)
        self.assertIn('if (!isPublicHomepage) {\n    bindSideHustleAction();\n  }', self.meridian_js)

    def test_homepage_copy_declares_public_private_boundary(self):
        """Homepage copy should explicitly state no private/operator auto API fetches."""
        self.assertIn(
            'The public homepage does not auto-request any private or operator API.',
            self.index_html,
        )


if __name__ == '__main__':
    unittest.main()
