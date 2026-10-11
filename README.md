# Termux packages for Ditto

An apt repository of [Termux](https://github.com/termux/termux-packages) packages rebuilt for
the terminal inside Ditto, the Android phone agent: the packages of Termux's main and root
repositories, for aarch64.

Termux packages hard-code their install prefix, so the ones published for the Termux app
(`/data/data/com.termux/files/usr`) can't be used by another app. These are built for Ditto's:

```
/data/data/com.wind.ditto.ai/files/libtermux/usr
```

and don't work in the Termux app either.

## Use

The repository is flat, and Ditto points apt at it by default:

```
deb [trusted=yes] https://github.com/WindySha/ditto-termux-packages/releases/download stable/
```

The index (`Packages`, `Release`) is in the [`stable` release](../../releases/tag/stable).
The package files are in `stable` and in the `pool-1`, `pool-2`, … releases, since a release
holds at most 1000 files; each `Filename` in the index is relative to the URL above. A
mirror of these releases, one directory per release, can be set in Ditto under Settings →
Terminal → Package repository (give the URL of the directory that contains `stable/`).

## Sources

Built from [termux/termux-packages](https://github.com/termux/termux-packages) at commit
[`e8cd1ae`](https://github.com/termux/termux-packages/commit/e8cd1ae62467ddc9af7cc4dd0b44ca2e355ef2b2)
with [`termux-packages.patch`](termux-packages.patch), which sets Ditto's package name and
prefix and makes a few build fixes. Each package's `build.sh` there names the upstream
source it was built from. Packages keep their upstream licenses, which they install under
`share/doc/<package>/`; the build scripts and patches are under the licenses described in
termux-packages' [LICENSE.md](https://github.com/termux/termux-packages/blob/master/LICENSE.md).

## Building

The [build workflow](.github/workflows/build.yml) builds in rounds. Each round takes the
recipes listed in [`ci/targets.txt`](ci/targets.txt) (those with packages in Termux's main and
root repositories) that aren't published yet and whose dependencies are, builds them in up to
20 jobs with termux-packages' Docker builder, downloading dependencies from this repository
([`ci/ci.patch`](ci/ci.patch)), publishes the result and starts the next round. Big recipes
get a run of their own. A recipe that fails twice is left out, along with what depends on
it; the [`ci` release](../../releases/tag/ci)'s `state.json` records why.

To build or rebuild particular recipes, after changing `termux-packages.patch` say:

```
gh workflow run build.yml -R WindySha/ditto-termux-packages -f packages="python ffmpeg"
```

Running it with no packages plans a round.
