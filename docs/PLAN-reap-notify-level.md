# Plan: reap notifications carry a severity

Goal: when `dofleet reap` deletes a droplet whose timer ran out, it should say so calmly. A failed delete should still be loud.
Today every reap message reaches the notify command as one bare argument, so a notifier whose default level is "critical"
(common for server-wide alert scripts) raises a red alert for a routine, expected cleanup.

## Why (measured 23 Nov 2026, no need to re-measure)

- 22 Nov 21:05:52 UTC: a test droplet `dfl-faas` was created with `--ttl 1m` while the Functions reaper was being verified (D9).
- 21:10:00 the host reap cron ran, deleted it (reap log: `expired` = `deleted` = one id, `failed` = []) and called
  `notify_cmd` with only the message. The host notifier defaults to `critical`, so the owner got a red alert at 21:10:14.
- The delete was correct (timer expired, droplet tagged `dofleet`). The bug is the missing severity, plus a message that does
  not say why it happened or whether anything needs doing.
- Gap found at the same time: a reap that fails to delete (`failed` non-empty, exit 1) sends no notification at all, although
  that droplet keeps costing money.

## Scope

- `notify_cmd` may contain the placeholders `{message}` and `{level}` in any argument. When no argument contains `{message}`,
  the message is appended as the last argument, exactly as today (existing configs keep working).
- Substitution is plain string replacement on those two tokens only (not `str.format`), so braces in droplet names cannot break it.
- Levels (documented vocabulary `info | warn | critical`):
  - timer-expired droplets deleted → `info`
  - droplets deleted because the month budget was exceeded with `budget_action = "reap"` → `warn`
  - one or more deletes failed → `critical`, one separate message naming them
- Message text says what, why and what to do, in both `locales/en.json` and `locales/ms.json` (same keys, same placeholders), e.g.
  EN: `dofleet reap deleted 1 droplet(s) whose timer ran out: dfl-faas. Expected; nothing to do. Need longer next time: dofleet extend <name> --ttl 2h`.
- The argv building lives in a small pure function `dofleet.notify.build_argv(cmd, message, level) -> list[str]` in a new module
  `src/dofleet/notify.py`; `cli._notify` calls it. Keep that module standard library only with no imports from the
  `dofleet` package (the host check loads it on its own).
- Docs: README.md and README.ms.md config section show the placeholder form; CHANGELOG.md gets an "Unreleased" entry;
  02-DECISIONS.md gets D11 (why, measured incident, levels).

Not in scope: the Functions reaper (`--notify-url` webhook), a new release to PyPI (goes out with the next normal release),
any change to what reap deletes.

## MULA DI SINI (start here): current state

**PELAN SIAP** (23 Nov 2026). Both slices done; nothing left that needs an agent.

- P1: `src/dofleet/notify.py` (`build_argv`), `cli._notify(message, level)` with `info` / `warn` / `critical`, en/ms texts,
  `tests/test_notify_level.py`, README/README.ms/CHANGELOG, decision record **D14**.
- P2 (host): the operator config now reads `notify_cmd = [<notifier>, "{message}", "{level}"]` (committed in the operator's
  own ops repository). Loading that config with the repo venv, `build_argv` returns `[<notifier>, <message>, "info"]` for a
  timer-expired reap and passes braces in names through literally. The next scheduled reap run after the switch completed
  normally (see Progress). Reap was not run by hand and no droplet was created.

Next: nothing. The change reaches PyPI with the next normal release (owner / regular release flow).

## Progress

| # | Slice | Who | Proof needed for done | Status |
|---|---|---|---|---|
| P1 | `src/dofleet/notify.py` + `cli._notify(message, level)` + failure/budget levels + clearer en/ms texts + `tests/test_notify_level.py` + README/README.ms/CHANGELOG/02-DECISIONS (D14) | agent | `tests/test_notify_level.py` drives `reap` through `cli.app` with a fake notify command (no module-level import of new names) and fails on the old code; `scripts/gate.sh` green; existing `test_reap_notifies_and_survives_errors` still passes | ✅ 23 Nov |
| P2 | [hos] switch the host's operator config to the placeholder form and confirm the next cron run | agent | host config contains `{message}` and `{level}`; `build_argv` on that config yields level `info` for a reap; next scheduled reap run exits 0 | ✅ 23 Nov |

## Tests P1 must contain (all through `cli.app`, fake API from `tests/fake_do.py`)

The `fake` fixture lives in `tests/test_cli.py`; move it to `tests/conftest.py` or define it in the new file. The new file
must import only names that already exist in the old code, so on the old code its tests run and fail (not a collection error).


1. Expired droplet + `notify_cmd = ["sh", "-c", "printf '%s|%s\n' \"$0\" \"$1\" >> LOG", "{message}", "{level}"]` → LOG has one line
   ending `|info`, the message names the droplet and does not contain the literal `{message}`.
2. A delete that fails with 500 → an extra line ending `|critical` naming that droplet; exit code 1 as today.
3. Budget over with `budget_action = "reap"` → level `warn`.
4. Old form `notify_cmd = ["sh", "-c", "echo \"$0\" >> LOG"]` → message still appended (backward compatible).
5. A droplet name containing `{level}` or `{}` is passed through literally.
6. Locale parity: en and ms have the same new keys and placeholders (the existing parity test should cover it; keep it green).

## Owner decisions

None blocking. Default if silent: the change ships in the next normal release; the host uses it at once through its editable install.

## Rollback

P1: `git revert <commit>` (old configs never depended on placeholders). P2: restore the previous `notify_cmd` line in the host config.
