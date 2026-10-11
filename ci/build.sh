#!/bin/bash
# Build recipes one at a time in termux-packages (the current directory), downloading their
# dependencies from the repository, and append "<recipe>\t<status>\t<seconds>" to the results
# file. Status is ok, failed, timeout or skipped (not started: out of time, or a dependency
# built earlier in this job failed).
#
#   ci/build.sh <results file> <log dir> <recipe>[@<dep>,<dep>...]...
#
# Environment: START_BEFORE and DEADLINE, as epoch seconds. Recipes aren't started after
# START_BEFORE, and a build still running at DEADLINE is killed.
set -u

results=$1
logs=$2
shift 2
mkdir -p "$logs"
touch "$results"

for spec in "$@"; do
	pkg=${spec%%@*}
	waits=""
	[[ $spec == *@* ]] && waits=${spec#*@}
	status=""
	for dep in ${waits//,/ }; do
		grep -qP "^\Q$dep\E\tok\t" "$results" || status=skipped
	done
	now=$(date +%s)
	(( now < START_BEFORE )) || status=skipped
	if [[ -n $status ]]; then
		printf '%s\t%s\t0\n' "$pkg" "$status" >> "$results"
		continue
	fi

	echo "::group::$pkg"
	rc=0
	timeout --kill-after=120 $(( DEADLINE - now )) \
		./scripts/run-docker.sh ./build-package.sh -I -C -a aarch64 "$pkg" > "$logs/$pkg.log" 2>&1 || rc=$?
	case $rc in
		0) status=ok ;;
		124|137) status=timeout ;;
		*) status=failed ;;
	esac
	took=$(( $(date +%s) - now ))
	printf '%s\t%s\t%s\n' "$pkg" "$status" "$took" >> "$results"
	if [[ $status == ok ]]; then
		rm -f "$logs/$pkg.log"
	else
		tail -n 100 "$logs/$pkg.log"
	fi
	echo "::endgroup::"
	echo "$pkg: $status in $(( took / 60 ))m"
	if [[ $status == timeout ]]; then
		docker rm -f termux-package-builder > /dev/null 2>&1 || :
	fi
done
