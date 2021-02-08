#!/bin/bash
set -eux

pushd "$1" >/dev/null
if [ -n "$(git status --porcelain)" ]; then
	git add --all
	git commit --amend --reset-author --message "${2:-automatic commit}"
	git push --force
fi
popd >/dev/null
