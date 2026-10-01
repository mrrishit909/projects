#!/bin/bash
# Publish a local git project to github.com/mrrishit909/<repo>, creating the repo if needed.
#
#   ./publish.sh <folder> <repo> "<one-line description>" [pages]
#
# Pushes the current branch to main. 'pages' also turns on GitHub Pages (main, root).
# Refuses to push if anything that would go public looks like a secret, a .env file or a >49 MB file.
# The GitHub token comes from the macOS keychain (git credential helper) and is never printed.
set -euo pipefail
dir=$1 repo=$2 desc=$3 pages=${4:-}
user=mrrishit909
email=73118361+mrrishit909@users.noreply.github.com
cd "$dir"

# 1. safety checks on everything this push makes public (all tracked files + the whole history)
if git ls-files | grep -E '(^|/)\.env$'; then echo "STOP: a .env file is tracked"; exit 1; fi
secret='(sk-ant-[A-Za-z0-9_-]{20,}|sk-proj-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{40,}|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16}|-----BEGIN [A-Z ]*PRIVATE KEY)'
# (no grep -q: it exits early, git log gets SIGPIPE, and pipefail would hide the match)
if git log -p HEAD | grep -E "$secret" >/dev/null; then echo "STOP: something in the git history looks like a secret"; exit 1; fi
big=$(git ls-files -z | xargs -0 du -k 2>/dev/null | awk '$1 > 49000 {print $2}')
if [ -n "$big" ]; then echo "STOP: files over 49 MB: $big"; exit 1; fi

# 2. new commits made here are attributed to the GitHub account, not a laptop hostname
git config user.name "Rishit Raj Mathur"
git config user.email "$email"

# 3. create the repo if it doesn't exist, then push
TOKEN=$(printf 'protocol=https\nhost=github.com\nusername=%s\n\n' "$user" | git credential fill | sed -n 's/^password=//p')
api() { curl -s -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" "$@"; }
code=$(api -o /dev/null -w '%{http_code}' "https://api.github.com/repos/$user/$repo")
if [ "$code" = 404 ]; then
  made=$(api -X POST https://api.github.com/user/repos -o /dev/null -w '%{http_code}' \
    -d "$(jq -n --arg n "$repo" --arg d "$desc" '{name:$n, description:$d}')")
  # 403 = token can't create repos: create an empty public repo named $repo on github.com, then re-run
  if [ "$made" != 201 ]; then echo "STOP: creating $repo failed (HTTP $made)"; exit 1; fi
  echo "created https://github.com/$user/$repo"
elif [ "$code" != 200 ]; then echo "STOP: GitHub API said HTTP $code (token expired or missing permission?)"; exit 1; fi

git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$user/$repo.git"
git push -u origin HEAD:main

# 4. GitHub Pages (409 = already on, which is fine)
if [ "$pages" = pages ]; then
  api -X POST "https://api.github.com/repos/$user/$repo/pages" -o /dev/null -w "pages -> HTTP %{http_code}\n" \
    -d '{"source":{"branch":"main","path":"/"}}'
fi
echo "published: https://github.com/$user/$repo"
