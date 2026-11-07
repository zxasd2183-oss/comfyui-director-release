# Owner-only offline verification of a private Studio delivery

After EP01 has actual, human-reviewed picture, audio and Chinese subtitles,
Director Studio can issue two **Microsoft-owner-only** downloads on the
Video Production page: the immutable MP4 and a provenance/QC JSON receipt.

Place both files in the same private folder on the owner's computer.
Do not use a downloaded JSON from another person's chat/email as evidence
of identity. The checksum proves only the pair's consistency, not who signed
or authorized the source document.

Run locally with Python 3 (network and Studio login are unnecessary):

    python3 studio/verify_private_delivery.py \
      --receipt /private/EP01-QC.json \
      --mp4 /private/EP01.mp4 \
      --project WaitingOffice --episode EP01

Optional deeper container/track validation, when ffprobe is installed:

    python3 studio/verify_private_delivery.py \
      --receipt /private/EP01-QC.json \
      --mp4 /private/EP01.mp4 \
      --project WaitingOffice --episode EP01 --check-streams

A successful result means the complete file bytes match the owner-downloaded
receipt, its SHA-256 checksum is internally consistent, and the recorded
revision was marked final-QC approved when the receipt was issued. With
--check-streams, the local MP4 is independently checked for video, AAC
audio, mov_text subtitles and the stated duration. It does **not** recheck
Studio's live database, confirm a producer's identity, grant publishing rights,
or indicate that GPU rendering occurred. The owner must separately authorize
any external release.

Failure exit code: 2. Success exit code: 0. No files are modified, no network
calls are made, and no GPU operations are invoked.
