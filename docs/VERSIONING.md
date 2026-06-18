# Versioning policy

## Tags

- `v1.4.0`, `v1.5.0`, ... -- semver-pinned stable releases. Consumers should pin to these for reproducible CI.
- `v1` -- moving tag that points at the latest `v1.x.x` release. Consumers who want automatic updates within v1 can use this; consumers who want strict reproducibility should use `v1.x.x` tags.
- `main` -- unstable development head. Do not pin consumers to `main`.

## When `v1` moves

`v1` only moves within the v1.x.x line. When v2.0.0 ships:

- `v1` stops moving and freezes at the last v1.x.x release.
- A new `v2` tag is created to point at v2.0.0 and moves within v2.x.x.
- Consumers pinned to `v1` keep their v1 behavior until they explicitly upgrade.

## Breaking-change discipline

Breaking changes only land on a major-version bump. For this project, "breaking" means:

- A check that previously WARNed now FAILs the build.
- A `validator.json` format key is removed or changes meaning.
- A CLI flag is removed or changes its default behavior.

Strictly additive changes are minor-version bumps: new checks that default to warn-only, new flags, new output modes, false-positive removal, expanded container block lists.

## Recommended consumer pinning

For CI configs in mod repos, two valid approaches:

- `ref: v1.5.0` -- strict pinning. CI is reproducible; you opt into each upgrade explicitly. Recommended for release workflows.
- `ref: v1` -- auto-update within v1.x. You get fixes and new warn-only checks automatically. Acceptable for validate-only workflows where a new warning does not break the build.

Never use `ref: main`.

---

## Decision pending -- three options for the `v1` tag strategy

The current state: `v1` is a moving tag force-updated to each new release. All seven consumer mod repos pin `ref: v1`. The policy above codifies this pattern with a breaking-change discipline. Before adopting it, three options are on the table.

**Option A -- moving `v1` within minor + patch (recommended)**

`v1` always points at the latest `v1.x.x`. Major-version bumps create a new moving tag (`v2`, `v3`, ...) and freeze the old one. This is the industry-standard pattern (GitHub Actions ecosystem uses this: `actions/checkout@v4`).

- Pro: consumers on `ref: v1` get bug fixes and new warn-only checks automatically.
- Pro: breaking changes never silently land on `ref: v1`; they require a new `v2` tag.
- Con: requires discipline to never force-update `v1` with a breaking change.

**Option B -- frozen `v1`, require explicit pinning**

Stop moving `v1` entirely. Publish `v1.5.0`, `v1.6.0`, etc. but do not update `v1`. Consumers must change their `ref:` to upgrade.

- Pro: maximum reproducibility. No consumer is ever surprised.
- Con: the seven existing consumer repos all pin `ref: v1`. They would stop receiving any updates until each is manually updated.

**Option C -- always-latest `v1` (status quo, no discipline)**

Continue force-updating `v1` to every release, including future major versions. Same as before Round 1.

- Pro: zero change from current practice.
- Con: a breaking change still silently breaks all consumers on their next CI run. This is the problem the audit flagged.

**Recommendation:** Option A. It preserves the existing `ref: v1` pinning in all consumer repos while guaranteeing that a breaking change can only land under a new `v2` tag. The only cost is enforcing the discipline.

No tags are moved in this session. Finn should confirm the chosen option before any tag operations.
