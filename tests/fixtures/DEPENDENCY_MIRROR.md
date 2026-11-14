# Blender dependency mirror regression fixtures

Unmodified upstream files; SPDX headers are retained. Tests are offline.

| Version | Immutable Blender commit | File | SHA-256 |
| --- | --- | --- | --- |
| 5.2.0 | `fbe6228777e7d9afefcd61a413844e790ae75db7` | `GNUmakefile` | `33d1694bbfc54fbf45fe630ad946639e52afc7a9fcfe2703deeeb4d1de078154` |
| 5.2.0 | same | `build_files/build_environment/cmake/download.cmake` | `b6cd865037c901ebcb10dab0b14e76cbbef5f8d67120a6d6bedf55948ab5d7c0` |
| 5.3.0 | `02f0899d78e374b63e7181d9061e1f7ab03419cc` | `GNUmakefile` | `618c136027eb3f90913cc06990fb6db1fd3014b24a52f454a188e9454d44e33c` |
| 5.3.0 | same | `build_files/build_environment/cmake/download.cmake` | `fe3a13bf3715d897bcb0a7f118ef286345d06ba97ab9904ed1854f99b35f5a17` |

Source URL template: `https://raw.githubusercontent.com/blender/blender/<commit>/<file>`.
Tags were resolved with `git ls-remote https://github.com/blender/blender.git refs/tags/v5.2.0 refs/tags/v5.3.0`.

`test_dependency_mirror.py` executes the unchanged make recipe against a tiny
CMake project, stubbing only dependency compilation. It separately executes the
unchanged `download_source` function (isolated from the full download call list)
to check valid and corrupt cached archives. The production configuration test
exercises an existing ON cache, version variation, and shell quoting. These are
not full dependency builds or network tests.
