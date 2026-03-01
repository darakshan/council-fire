# The Council Fire — Site Management
# Run `just` to see available recipes.
# Requires: python3, just  (brew install just)

site_dir := justfile_directory()

# Rebuild the entire site from Apple Notes
build:
    python3 {{site_dir}}/generate.py

# Install / deploy the site (configure target below)
install: build
    @echo "Deploy target not yet configured."
    @echo "Options: GitHub Pages, Netlify, rsync to a server..."
    @echo "Edit the 'install' recipe in justfile when ready."
