#!/bin/bash
set -ex

pip3 install -r .github/requirements.txt

git worktree add -b gh-pages gh-pages origin/gh-pages
git worktree add -b state state origin/state

.github/cron.py

git config --global user.name 'GitHub Actions'
git config --global user.email "$(whoami)@$(hostname --fqdn)"
git config --global http.https://github.com/.extraheader "Authorization: Basic $(echo -n "dummy:${GITHUB_PERSONAL_ACCESS_TOKEN}" | base64 --wrap=0)"

push_if_modified() {
	pushd "$1" 2>/dev/null
	if [ -n "$(git status --porcelain)" ]; then
		git add --all
		git commit --amend --reset-author --message 'automatic commit'
		git push --force
	fi
	popd 2>/dev/null
}

push_if_modified gh-pages
push_if_modified state
