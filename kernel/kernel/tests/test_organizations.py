import importlib.util
import pathlib
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[2]
ORGANIZATIONS_PATH = ROOT / 'kernel' / 'organizations.py'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


organizations = _load_module('kernel_organizations_test', ORGANIZATIONS_PATH)
update_org = organizations.update_org

class TestOrganizationsUpdateOrg(unittest.TestCase):
    def setUp(self):
        self.mock_data = {
            'organizations': {
                'org_1': {
                    'id': 'org_1',
                    'name': 'Test Org',
                    'plan': 'free',
                    'status': 'active',
                    'other_field': 'value'
                }
            }
        }

    @patch.object(organizations, 'load_orgs')
    @patch.object(organizations, 'save_orgs')
    def test_update_org_success(self, mock_save, mock_load):
        mock_load.return_value = self.mock_data

        update_org('org_1', name='Updated Org', plan='pro', status='suspended')

        self.assertEqual(self.mock_data['organizations']['org_1']['name'], 'Updated Org')
        self.assertEqual(self.mock_data['organizations']['org_1']['plan'], 'pro')
        self.assertEqual(self.mock_data['organizations']['org_1']['status'], 'suspended')
        mock_save.assert_called_once_with(self.mock_data)

    @patch.object(organizations, 'load_orgs')
    def test_update_org_not_found(self, mock_load):
        mock_load.return_value = self.mock_data

        with self.assertRaisesRegex(ValueError, 'Organization not found: org_2'):
            update_org('org_2', name='Updated Org')

    @patch.object(organizations, 'load_orgs')
    def test_update_org_invalid_plan(self, mock_load):
        mock_load.return_value = self.mock_data

        with self.assertRaisesRegex(ValueError, 'Invalid plan: invalid_plan'):
            update_org('org_1', plan='invalid_plan')

    @patch.object(organizations, 'load_orgs')
    def test_update_org_invalid_status(self, mock_load):
        mock_load.return_value = self.mock_data

        with self.assertRaisesRegex(ValueError, 'Invalid status: invalid_status'):
            update_org('org_1', status='invalid_status')

    @patch.object(organizations, 'load_orgs')
    @patch.object(organizations, 'save_orgs')
    def test_update_org_partial_update(self, mock_save, mock_load):
        mock_load.return_value = self.mock_data

        update_org('org_1', plan='pro')

        self.assertEqual(self.mock_data['organizations']['org_1']['name'], 'Test Org')
        self.assertEqual(self.mock_data['organizations']['org_1']['plan'], 'pro')
        self.assertEqual(self.mock_data['organizations']['org_1']['status'], 'active')
        mock_save.assert_called_once_with(self.mock_data)

    @patch.object(organizations, 'load_orgs')
    @patch.object(organizations, 'save_orgs')
    def test_update_org_ignores_other_fields(self, mock_save, mock_load):
        mock_load.return_value = self.mock_data

        update_org('org_1', other_field='new_value', unsupported_field='unsupported')

        self.assertEqual(self.mock_data['organizations']['org_1']['other_field'], 'value')
        self.assertNotIn('unsupported_field', self.mock_data['organizations']['org_1'])
        mock_save.assert_called_once_with(self.mock_data)

if __name__ == '__main__':
    unittest.main()
