# Blender OSL regression fixture

`osl.cmake` is an unmodified copy of Blender's
`build_files/build_environment/cmake/osl.cmake` at tag `v5.3.0`, resolved via
`git ls-remote https://github.com/blender/blender.git refs/tags/v5.3.0` to
commit `02f0899d78e374b63e7181d9061e1f7ab03419cc`.

Immutable source:
https://raw.githubusercontent.com/blender/blender/02f0899d78e374b63e7181d9061e1f7ab03419cc/build_files/build_environment/cmake/osl.cmake

SHA-256: `534ccae78a3160fb24ace3163e82982c29891d1015e3e6b8a624490b6ddd6b6e`

The upstream copyright and GPL-2.0-or-later SPDX header are preserved.
Tests use this local copy without network access.

## Dependency parallelism fixture

`make_deps_wrapper.sh` is an unmodified copy of
`build_files/build_environment/linux/make_deps_wrapper.sh` at the same commit:
https://raw.githubusercontent.com/blender/blender/02f0899d78e374b63e7181d9061e1f7ab03419cc/build_files/build_environment/linux/make_deps_wrapper.sh

SHA-256: `84dccce78a76c648503832afc1149ff5b1b35f162bd9d86a8c7a27d05595d20f`

The `v5.2.0` wrapper has the identical digest, so the parallelism regression uses
this copy with both versioned GNUmakefile fixtures. The upstream copyright and
GPL-2.0-or-later SPDX header are preserved.
