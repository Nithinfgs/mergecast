#!/usr/bin/env bash
# .git/hooks/pre-push — refuse to push while a hard conflict is forecast between worktrees.
exec mergecast --fail-on conflict --no-color
