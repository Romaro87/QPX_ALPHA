#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
echo "QPX SAFE WEEKEND CLEANUP — nothing is deleted."
ARCHIVE="archive/local_research_20260808"
ART="archive/local_artifacts_20260808"
mkdir -p "$ARCHIVE" "$ART"
while IFS= read -r -d '' f; do
  case "$f" in
    QPX_INSTALL_*.py|QPX_RUN_*.py|QPX_COMPARE_*.py|QPX_V*.py) echo "Archive: $f"; mv -- "$f" "$ARCHIVE/";;
  esac
done < <(git ls-files --others --exclude-standard -z -- . 2>/dev/null || true)
for f in "0.844464" "12.76%" "37.80%" "820" "=" "himBHs2,134.25"; do
  if [ -f "$f" ] && ! git ls-files --error-unmatch "$f" >/dev/null 2>&1; then echo "Archive artifact: $f"; mv -- "$f" "$ART/"; fi
done
touch .gitignore
if ! grep -qF "# BEGIN QPX LOCAL GENERATED" .gitignore; then
cat >> .gitignore <<'EOF'

# BEGIN QPX LOCAL GENERATED
reports/
research_data/
logs/
backups/
archive/
qpx_gui_runtime/
__pycache__/
*.pyc
*.bak
*.pre_symbol_config.bak
# END QPX LOCAL GENERATED
EOF
fi
printf '%s\n' "Preserved untracked research/install scripts moved here by QPX_WEEKEND_CLEANUP.sh on 2026-08-08." > "$ARCHIVE/README.txt"
echo
git status --short --untracked-files=no || true
echo "Cleanup complete."
