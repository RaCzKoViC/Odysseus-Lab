# Odysseus-Lab fork policy

Odysseus-Lab is an independently maintained distribution of
[Odysseus](https://github.com/odysseus-dev/odysseus). It is not endorsed by or
operated by the upstream maintainers.

## Lineage

- Upstream repository: `https://github.com/odysseus-dev/odysseus`
- Imported branch: `dev`
- Imported commit: `9d5c0319149bfb69ce22a35f37cf17debaa5f14b`
- Imported Odysseus version: `1.0.3`
- First Odysseus-Lab release line: `0.1.x`

The exact tracked baseline is also stored in [`UPSTREAM_BASE`](UPSTREAM_BASE).
The review and synchronization procedure is documented in
[`docs/UPSTREAM.md`](docs/UPSTREAM.md).

## Compatibility contract

Odysseus-Lab 0.1 deliberately retains upstream command names, `ODYSSEUS_*`
environment variables, the `data/` layout, persistent browser keys, Docker
service names, backup formats, and Chroma collection names. User-facing product
identity and operational tooling may use the Odysseus-Lab name.

Changes to a retained interface require a migration path and regression tests.
Lab-only features should be additive and isolated from upstream conflict
hotspots whenever practical.

## License

The project remains licensed under GNU AGPL-3.0-or-later. All original
copyright and third-party notices remain in place. Operators who provide a
modified version over a network are responsible for satisfying the AGPL source
availability requirements. See [`LICENSE`](LICENSE) and
[`ACKNOWLEDGMENTS.md`](ACKNOWLEDGMENTS.md).
