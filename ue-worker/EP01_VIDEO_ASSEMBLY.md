# EP01 final-video assembly (branch-only change)

This module **does not fabricate video**. It assembles **only real, fully validated** clips and mixed audio into the intended 160-second EP01 H.264/AAC MP4.

## Required files

Under `DIRECTOR_UE_WORKSPACE` (default `C:/DirectorVirtualStudio`):

- `Outputs/EP01/Clips/SH01.mp4` through `SH31.mp4`: all 31 real shots, each 1080×1920 at 24 fps with the precise frozen shot frame count.
- `Outputs/EP01/Audio/MixedAudio.wav`: 160 seconds of 48 kHz stereo uncompressed PCM final mix.

There is no script option to accept arbitrary shot counts, change FPS or alter the locked episode. A missing/corrupt/short clip, missing audio or output name collision prevents creation of a misleading final MP4. The operator must install a trusted `ffmpeg`/`ffprobe` locally; signed updater/Worker do not install executable dependencies.

### Local operator command

```powershell
python .\episode_final_assembler.py --workspace C:\DirectorVirtualStudio --dry-run
python .\episode_final_assembler.py --workspace C:\DirectorVirtualStudio
```

Result, only after all inputs actually exist:
`C:\DirectorVirtualStudio\Outputs\EP01\Final\WaitingOffice_EP01_v001.mp4`

Final MP4 is H.264 video at 1080×1920/24 fps, exactly 3,840 decoded frames, with encoded 48 kHz AAC from provided mix. It writes a SHA-256/shot-input receipt. **This is only the technical assembly step**: facial identity, scene continuity, performance, subtitles, export QC and rights require separate human or automated validation. No H3/MetaHuman model is generated; no logos, passwords or cloud GPU controls are touched.

This code is not wired into the MCP job allowlist pending real asset binding and an explicit release review. The existing Worker 0.7.2 production service is unchanged.
