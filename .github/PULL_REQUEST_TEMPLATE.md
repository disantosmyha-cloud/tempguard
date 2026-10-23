## What changed

## Failure mode

If this change touches sensors, shutdown, terminate or alert delivery, what happens when it fails?

## Verification

```powershell
python -m unittest discover -s tests -v
ruff check --select E9,F63,F7,F82 .
```

- [ ] No secrets, `config.local.yaml`, `secrets.dat`, logs or runtime data included
- [ ] Docs updated if behavior changed
- [ ] Safety-related behavior has a test
