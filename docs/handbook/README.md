# User handbook / Nutzerhandbuch

This directory contains the reviewed source for the public GitHub Wiki user
handbook in German and English. The site-specific family PDF is deliberately
not published: it contains private infrastructure details.

- [Deutsch](wiki/DE-Start.md)
- [English](wiki/EN-Start.md)
- [German blank emergency printout](print/Emergency-Secrets-DE.pdf)
- [English blank emergency printout](print/Emergency-Secrets-EN.pdf)

**Only blank forms belong in this repository or the wiki.** Completed forms,
private inventories, recovery codes, passwords and keys remain offline or in a
protected private system. Fill the emergency form by hand after printing. For
secrets already managed by a vault/password manager, record a reference rather
than duplicate the value. The form is not a replacement for a recoverable vault.

## Editing and publishing

Edit matching `DE-*` and `EN-*` pages together. Keep both editions aligned on
instructions, scope and limitations. Repository documentation describes available
code; each deployment needs its own private inventory and restore evidence.

GitHub wikis use a separate Git repository. The ordinary repository's REST
Contents API cannot edit wiki pages. Create the first wiki page through GitHub
if the wiki has not been initialized, then use an existing authenticated Git
setup with write access:

For a new empty wiki, create `Home` with the following body to identify it as
navigation intentionally owned by this handbook:

```html
<!-- bergen-platform-handbook: managed -->
```

The PDF download links target `main`; merge the reviewed source and blank PDFs
there before publishing wiki pages. For an existing wiki, inspect and integrate
navigation rather than adding ownership markers to someone else's pages.

```sh
python3 scripts/publish_handbook_wiki.py --target ../bergen-platform-wiki
```

This prepares a wiki checkout and a diff. It does not commit or push. Inspect
the diff, preserving any existing unrelated wiki pages. To publish this reviewed
handbook explicitly:

```sh
python3 scripts/publish_handbook_wiki.py \
  --target ../bergen-platform-wiki --publish
```

The publisher checks repository identity, uses a clean working tree, updates
with fast-forward only, and never force-pushes. Existing handbook-owned files
are updated, but unrelated pages are retained. A pre-existing `Home.md`,
`_Sidebar.md` or `_Footer.md` without the handbook ownership marker stops the
operation; integrate that navigation manually instead of overwriting it.
An initialized wiki and valid authentication are prerequisites. Never paste a
token into the command line or a repository file; use your existing credential
manager or authenticated SSH setup.

## Print templates

The two two-page A4 PDFs are blank, printable, and contain no interactive
secret fields. Their source is `scripts/build_emergency_printouts.py`.
Install the declared optional documentation dependency from
`docs/handbook/requirements-print.txt` to regenerate them.

## Validation

```sh
python3 scripts/check_handbook.py
python3 -m unittest discover -s tests -p 'test_publish_handbook_wiki.py'
```

The checker verifies language pairing, navigation/link destinations, public
examples and common private-address/domain patterns. It is a
focused guard against accidentally republishing private deployment details;
it is not a general secret-detection system. Review new content for secrets.

Source baseline: repository main `7b465fad95be476e853f0b74e9e86e1d125fd4f5`;
public handbook edition 1.0, 2026-10-14. No private runtime validation is claimed.
