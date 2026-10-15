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
