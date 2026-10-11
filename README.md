# Termux packages for Ditto

An apt repository of [Termux](https://github.com/termux/termux-packages) packages rebuilt for
the terminal inside Ditto, the Android phone agent:
Python, pip, numpy, lxml, ffmpeg, ImageMagick, Ghostscript, Tesseract and what they depend
on, for aarch64.

Termux packages hard-code their install prefix, so the ones published for the Termux app
(`/data/data/com.termux/files/usr`) can't be used by another app. These are built for Ditto's:

```
/data/data/com.wind.ditto.ai/files/libtermux/usr
```

and don't work in the Termux app either.

## Use

The packages are the assets of the [`stable` release](../../releases/tag/stable). The
repository is flat, and Ditto points apt at it by default:

```
deb [trusted=yes] https://github.com/WindySha/ditto-termux-packages/releases/download stable/
```

A mirror of the release's files, in a `stable/` directory, can be set in Ditto under
Settings → Terminal → Package repository (give the URL of the directory that contains
`stable/`).

## Sources

Built from [termux/termux-packages](https://github.com/termux/termux-packages) at commit
[`e8cd1ae`](https://github.com/termux/termux-packages/commit/e8cd1ae62467ddc9af7cc4dd0b44ca2e355ef2b2)
with [`termux-packages.patch`](termux-packages.patch), which sets Ditto's package name and
prefix and makes a few build fixes. Each package's `build.sh` there names the upstream
source it was built from. Packages keep their upstream licenses, which they install under
`share/doc/<package>/`; the build scripts and patches are under the licenses described in
termux-packages' [LICENSE.md](https://github.com/termux/termux-packages/blob/master/LICENSE.md).

The repository is built and published with Ditto's `scripts/termux/build-apt-repo.sh`.
