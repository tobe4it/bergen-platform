"""Keep only package identity and version changes; never module stdout."""
def package_delta(before, after):
    def normalized(packages):
        return {name: sorted(str(p['version']) + '-' + str(p.get('release', '')) +
                             '.' + str(p.get('arch', '')) for p in entries)
                for name, entries in packages.items()}
    old, new = normalized(before), normalized(after)
    return [{'name': name, 'old': old.get(name, []), 'new': new.get(name, [])}
            for name in sorted(old.keys() | new.keys()) if old.get(name) != new.get(name)]


class FilterModule:
    def filters(self):
        return {'system_update_delta': package_delta}
