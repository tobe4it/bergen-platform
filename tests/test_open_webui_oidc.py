import unittest
from pathlib import Path
import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]

class OidcConfigurationTests(unittest.TestCase):
    def test_rendered_environment_preserves_secret_and_recovery(self):
        template = (ROOT / 'ansible/templates/open-webui/oidc.env.j2').read_text()
        values = dict(open_webui_oidc_public_url='https://ai.example.net',
                      open_webui_oidc_client_id='client',
                      vault_open_webui_oidc_client_secret='literal$secret#with=equals',
                      open_webui_oidc_discovery_url='https://sso.example.net/.well-known/openid-configuration')
        rendered = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(template).render(**values)
        env = dict(line.split('=', 1) for line in rendered.splitlines() if line and not line.startswith('#'))
        self.assertEqual(env['OAUTH_CLIENT_SECRET'], values['vault_open_webui_oidc_client_secret'])
        self.assertEqual(env['OPENID_REDIRECT_URI'], 'https://ai.example.net/oauth/oidc/callback')
        self.assertEqual(env['OAUTH_SCOPES'], 'openid email groups')
        self.assertEqual(env['ENABLE_LOGIN_FORM'], 'true')
        self.assertEqual(env['DEFAULT_USER_ROLE'], 'pending')
        self.assertEqual(env['OAUTH_MERGE_ACCOUNTS_BY_EMAIL'], 'false')
        self.assertEqual(env['ENABLE_OAUTH_ROLE_MANAGEMENT'], 'false')

    def test_secret_is_protected_and_dropin_is_additive(self):
        play = yaml.safe_load((ROOT / 'ansible/playbooks/configure-open-webui-oidc.yml').read_text())[0]
        writes = [t for t in play['tasks'] if 'ansible.builtin.template' in t]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0]['no_log'])
        self.assertFalse(writes[0]['diff'])
        self.assertEqual(writes[0]['ansible.builtin.template']['mode'], '0600')
        copy = next(t['ansible.builtin.copy'] for t in play['tasks'] if 'ansible.builtin.copy' in t)
        self.assertIn('EnvironmentFile=', copy['content'])
        self.assertNotIn('Image=', copy['content'])
        self.assertNotIn('Volume=', copy['content'])
        self.assertEqual(len(play['tasks'][0]['ansible.builtin.assert']['that']), 3)

    def test_group_sync_is_opt_in_without_role_promotion_or_group_creation(self):
        template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
            (ROOT / 'ansible/templates/open-webui/oidc.env.j2').read_text())
        values = dict(open_webui_oidc_public_url='https://ai.example.net',
                      open_webui_oidc_client_id='client',
                      vault_open_webui_oidc_client_secret='secret',
                      open_webui_oidc_discovery_url='https://sso.example.net/.well-known/openid-configuration')
        for enabled, expected in [(None, 'false'), (False, 'false'), ('false', 'false'), (True, 'true'), ('true', 'true')]:
            with self.subTest(enabled=enabled):
                settings = dict(values)
                if enabled is not None:
                    settings['open_webui_oidc_group_management'] = enabled
                env = dict(line.split('=', 1) for line in template.render(**settings).splitlines()
                           if line and not line.startswith('#'))
                self.assertEqual(env['ENABLE_OAUTH_GROUP_MANAGEMENT'], expected)
                self.assertEqual(env['ENABLE_OAUTH_GROUP_CREATION'], 'false')
                self.assertEqual(env['ENABLE_OAUTH_ROLE_MANAGEMENT'], 'false')
                self.assertEqual(env['DEFAULT_USER_ROLE'], 'pending')
                self.assertNotIn('vault_open_webui_admin_token', template.render(**settings))

    def test_group_provisioning_is_additive_and_token_is_not_logged(self):
        play = yaml.safe_load((ROOT / 'ansible/playbooks/configure-open-webui-oidc.yml').read_text())[0]
        group_block = next(t for t in play['tasks'] if 'block' in t)
        self.assertTrue(group_block['no_log'])
        api_tasks = [t for t in group_block['block'] if 'ansible.builtin.uri' in t]
        mutations = [t for t in api_tasks if t['ansible.builtin.uri'].get('method', 'GET') != 'GET']
        self.assertEqual(len(mutations), 1)
        create = mutations[0]
        self.assertTrue(create['ansible.builtin.uri']['url'].endswith('/groups/create'))
        self.assertEqual(create['ansible.builtin.uri']['body']['permissions'], {'workspace': {}})
        self.assertIn('oidc_existing_groups', create['when'])
        for task in api_tasks:
            self.assertTrue(task['ansible.builtin.uri']['url'].startswith('http://127.0.0.1:3000/'))
            self.assertEqual(task['ansible.builtin.uri']['follow_redirects'], 'none')
            self.assertFalse(task['ansible.builtin.uri']['use_proxy'])
