#!/bin/bash
set -ex

git config user.name 'GitHub Actions'
git config user.email "$(whoami)@$(hostname --fqdn)"
git config http.https://github.com/.extraheader "Authorization: Basic $(echo -n "dummy:${GITHUB_PERSONAL_ACCESS_TOKEN}" | base64 --wrap=0)"

push_if_modified() {
	pushd "$1" >/dev/null
	if [ -n "$(git status --porcelain)" ]; then
		git add --all
		git commit --amend --reset-author --message 'automatic commit'
		git push --force
	fi
	popd >/dev/null
}

push_if_modified gh-pages
push_if_modified state
