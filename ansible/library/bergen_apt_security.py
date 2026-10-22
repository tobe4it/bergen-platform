#!/usr/bin/python
"""Security-origin APT updates with exact version pins and no removals."""
from ansible.module_utils.basic import AnsibleModule


def choose_versions(cache, held, origins, codename, compare):
    selected, deferred = [], []
    for package in cache:
        if not package.is_installed:
            continue
        versions = [v for v in package.versions if
                    compare(v.version, package.installed.version) > 0 and
                    any(o.trusted and o.origin in origins and
                        (o.archive == codename + '-security' or
                         o.codename == codename + '-security') for o in v.origins)]
        if not versions:
            continue
        best = versions[0]
        for version in versions[1:]:
            if compare(version.version, best.version) > 0:
                best = version
        item = {'name': package.name, 'old': package.installed.version, 'new': best.version}
        (deferred if package.name in held else selected).append(item)
    return sorted(selected, key=lambda p: p['name']), sorted(deferred, key=lambda p: p['name'])


def main():
    module = AnsibleModule(argument_spec={
        'apply': {'type': 'bool', 'default': False},
        'origins': {'type': 'list', 'elements': 'str', 'required': True},
        'codename': {'type': 'str', 'required': True},
    }, supports_check_mode=True)
    try:
        import apt
        import apt_pkg
        cache = apt.Cache()
        if not any(o.trusted and o.origin in module.params['origins'] and
                   (o.archive == module.params['codename'] + '-security' or
                    o.codename == module.params['codename'] + '-security')
                   for p in cache for v in p.versions for o in v.origins):
            module.fail_json(msg='NO_TRUSTED_SECURITY_SUITE_IN_CACHE')
        rc, out, _ = module.run_command(['apt-mark', 'showhold'])
        if rc:
            module.fail_json(msg='APT_HOLD_QUERY_FAILED')
        selected, held = choose_versions(cache, set(out.split()), module.params['origins'],
                                         module.params['codename'], apt_pkg.version_compare)
        if not selected or not module.params['apply'] or module.check_mode:
            module.exit_json(changed=False, candidates=selected, held=held)
        pins = [p['name'] + '=' + p['new'] for p in selected]
        base = ['apt-get', '--no-remove', '--only-upgrade',
                '-o', 'Dpkg::Options::=--force-confdef',
                '-o', 'Dpkg::Options::=--force-confold']
        rc, _, _ = module.run_command(base + ['--simulate', 'install'] + pins)
        if rc:
            module.fail_json(msg='APT_PLAN_REFUSED', candidates=selected, held=held)
        rc, _, _ = module.run_command(base + ['--assume-yes', 'install'] + pins,
                                      environ_update={'DEBIAN_FRONTEND': 'noninteractive', 'NEEDRESTART_MODE': 'l'})
        if rc:
            module.fail_json(msg='APT_UPDATE_FAILED_PARTIAL_CHANGES_POSSIBLE', changed=True,
                             candidates=selected, held=held)
        cache.open(None)
        if any(not cache[p['name']].is_installed or cache[p['name']].installed.version != p['new'] for p in selected):
            module.fail_json(msg='APT_TARGET_VERSION_NOT_REACHED', changed=True,
                             candidates=selected, held=held)
        module.exit_json(changed=True, candidates=selected, held=held)
    except ImportError:
        module.fail_json(msg='PYTHON3_APT_REQUIRED')


if __name__ == '__main__':
    main()
