# Director UE Worker signed update channel

This branch is the **public signed-manifest transport**, not a trusted
instruction source. The Windows updater accepts only a strictly formatted
`channel.json` whose Ed25519 signature verifies against the administrator
pinned public key. Every ZIP is independently SHA-256 and size checked, and
each ZIP may contain only the eight reviewed UE Worker scripts.

**There is intentionally no channel.json yet.** A trusted release workflow
will publish it once a dedicated signing key is provisioned, a reviewed
version is merged to main, and the release package is created. Until then
the scheduled updater exits without changing Worker code.

Neither a GitHub commit nor a raw download URL by itself authorizes code
execution. Never store private signing keys on this branch.
