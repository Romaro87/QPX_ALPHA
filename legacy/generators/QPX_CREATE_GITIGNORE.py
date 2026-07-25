from pathlib import Path

ROOT = Path("/storage/emulated/0/QPX_ALPHA")

gitignore = """
# Python
__pycache__/
*.py[cod]
*.pyo

# Logs
logs/*.log

# Cache
.cache/
.pytest_cache/

# IDE
.vscode/
.idea/

# Android
*.apk

# OS
.DS_Store
Thumbs.db

# Temporary
*.tmp
*.bak
"""

(ROOT / ".gitignore").write_text(gitignore.strip() + "\n")

print(".gitignore created")