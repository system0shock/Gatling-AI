# Methodology publish guard

This stdlib-only tool prepares a Confluence patch, records an explicit local
publication approval, and validates that the approved methodology and fixed
Confluence page version have not changed before a host-supplied publisher acts.

```powershell
python tools/methodology_publish/methodology_publish.py prepare --methodology methodology.md --page-snapshot page.json --out-dir run
python tools/methodology_publish/methodology_publish.py approve --descriptor run/publish-descriptor.json --approved-by v.salnikov --out run/publish-approval.json
python tools/methodology_publish/methodology_publish.py validate --methodology methodology.md --page-snapshot page.json --approval run/publish-approval.json
# Fresh host page-read form; page-snapshot and fresh-page-id/fresh-page-version are mutually exclusive
python tools/methodology_publish/methodology_publish.py validate --methodology methodology.md --fresh-page-id 123 --fresh-page-version 7 --approval run/publish-approval.json
```

The fresh form accepts only the host page-read response's `page_id` and numeric
`version`; it writes no transient repository artifact.


The tool does not publish to Confluence or select a page. The host publisher
uses the validated descriptor and its separately supplied write capability.
