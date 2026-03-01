# The Council Fire — Site Management
# Run `just` to see available recipes.
# Requires: python3, just  (brew install just)

site_dir := justfile_directory()

# Rebuild the entire site from Apple Notes
build:
    python3 {{site_dir}}/generate.py

# Deploy the site to GitHub Pages
install: build
    git -C {{site_dir}} add -A
    git -C {{site_dir}} diff --cached --quiet || git -C {{site_dir}} commit -m "Site update $(date '+%Y-%m-%d %H:%M')"
    git -C {{site_dir}} push origin master
