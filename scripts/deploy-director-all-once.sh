#!/usr/bin/env bash
# One operator-triggered VPS deployment of Director Hub + Studio production UI.
# NEVER powers on a GPU, sends a Comfy prompt or updates a shut-down GPU host.
set -Eeuo pipefail
umask 077
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 2; }
usage() {
  cat <<'EOF'
Usage: bash scripts/deploy-director-all-once.sh [--check]
Run on the VPS as the normal sudo-capable user, from the Git clone.
--check: read-only repository and service validation; NO pull/installation.
Default: fast-forward pull, offline tests, optional ffprobe install, safe Hub
upgrade, safe Studio upgrade, public HTTP and ownership checks.
GPU host deployment and any real rendering are NOT performed.
EOF
}
[[ $# -le 1 ]] || die "Unknown argument"
if (( $# == 1 )); then
  [[ "$1" == "--check" || "$1" == "--help" ]] || die "Unknown argument"
  if [[ "$1" == "--help" ]]; then usage;exit 0;fi
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[[ "$EUID" -ne 0 ]] || die "Run as normal VPS user; script uses sudo only for protected system operations"
[[ -d .git && -f studio/upgrade-v09.sh && -f vps-control/install-hub-v06.sh ]] ||
    die "Expected existing Director Studio Git checkout on VPS"
[[ "$(git branch --show-current)" == "main" ]] || die "Expected checked-out main branch"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] ||
    die "Tracked local modifications exist; refusing to overwrite"
for name in director-hub-mcp director-hub-bridge director-studio nginx; do
  systemctl is-active --quiet "$name" || die "Required existing service inactive: $name"
done
if (( $#==1 )); then
  printf 'CHECK OK: local repository and four existing services ready. No deployment performed.\n'
  exit 0
fi
[[ -x /usr/bin/python3 ]] || die "System Python missing"
[[ -x /usr/bin/curl ]] || die "curl missing"
echo 'Director full-feature upgrade: retrieving fast-forward Git main...'
git pull --ff-only
[[ -z "$(git status --porcelain --untracked-files=no)" ]] ||
  die "Working tree is dirty after pull"
DEPLOY_SHA="$(git rev-parse HEAD)"
printf 'DEPLOY SHA: %s\n' "$DEPLOY_SHA"
required_modules=(
  video_results.py picture_cuts.py picture_cut_jobs.py
  audio_stems.py audio_master.py audio_master_jobs.py
  subtitle_tracks.py release_candidates.py release_jobs.py
)
required_tests=(
  test_video_results.py test_picture_cuts.py test_picture_cut_jobs.py
  test_audio_stems.py test_audio_master.py test_subtitle_tracks.py
  test_release_candidates.py
)
for module in "${required_modules[@]}"; do
  [[ -f "studio/$module" ]] || die "Required Studio source module absent: $module"
done
for test_file in "${required_tests[@]}"; do
  [[ -f "studio/tests/$test_file" ]] || die "Required Studio regression test absent: $test_file"
done
[[ -f video-pipeline/director_video.py ]] ||
  die "Required video production runner missing"
echo 'All current audio/video/subtitle/release modules and test suites present.'
if [[ ! -x /usr/bin/ffprobe || ! -x /usr/bin/ffmpeg ]]; then
  echo 'Installing local FFmpeg/FFprobe for mandatory actual MP4 verification...'
  sudo env DEBIAN_FRONTEND=noninteractive apt-get update -qq
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg
fi
[[ -x /usr/bin/ffprobe && -x /usr/bin/ffmpeg ]] ||
  die "FFmpeg/FFprobe required for media verification tests"
echo 'Running local Studio unit/integration tests (no GPU)...'
python3 -m compileall -q studio video-pipeline
if command -v node >/dev/null 2>&1; then node --check studio/studio.js; fi
python3 -m unittest discover -s studio/tests -p 'test_*.py' -q
echo 'Running local video planner/clip archive tests (no GPU)...'
python3 -m unittest discover -s video-pipeline/tests -p 'test_*.py' -q
echo 'Upgrading isolated Hub, preserving approval state...'
sudo bash vps-control/install-hub-v06.sh
echo 'Upgrading Studio with its database-preserving backup/rollback...'
sudo bash studio/upgrade-v09.sh
for name in director-hub-mcp director-hub-bridge director-studio nginx; do
  systemctl is-active --quiet "$name" || die "Service did not recover: $name"
done
status_code="$(curl --silent --show-error --location --output /dev/null \
  --write-out '%{http_code}' --max-time 20 'https://jipite.borealos.cn/studio/')"
[[ "$status_code" == "200" ]] || die "Studio homepage returned $status_code (expected 200)"
private_paths=(
  '/studio/api/v1/video-results?project=WaitingOffice&episode=EP01&shot=01'
  '/studio/api/v1/picture-cuts?project=WaitingOffice&episode=EP01'
  '/studio/api/v1/audio-stems?project=WaitingOffice&episode=EP01'
  '/studio/api/v1/av-master?project=WaitingOffice&episode=EP01'
  '/studio/api/v1/subtitles?project=WaitingOffice&episode=EP01'
  '/studio/api/v1/release?project=WaitingOffice&episode=EP01'
)
for endpoint in "${private_paths[@]}"; do
  anonymous="$(curl --silent --show-error --output /dev/null \
    --write-out '%{http_code}' --max-time 20 \
    "https://jipite.borealos.cn$endpoint")"
  [[ "$anonymous" == "401" ]] ||
    die "Anonymous private media API returned $anonymous rather than 401: $endpoint"
done
echo 'Six private media APIs deny anonymous requests with HTTP 401.'
echo 'SUCCESS: VPS Hub+Studio deployed and verified; current repository SHA:'
printf '  %s\n' "$DEPLOY_SHA"
echo 'GPU remains untouched. Real H3 compatibility, local executor installation,'
echo 'Comfy submission and artistic clip approval require separate explicit review.'
