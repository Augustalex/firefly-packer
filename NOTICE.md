# Licenses and provenance

The original Python packager, Objective-C launcher, tests, configuration example,
and documentation use the MIT license in LICENSE.

`patches/firefly-emulator-window-title.patch` includes and modifies portions of
Firefly Zero emulator 0.15.0, copyright its upstream contributors. That patch
is under GPL-3.0, with the license text in `patches/GPL-3.0.txt`.
Upstream: https://github.com/firefly-zero/firefly-emulator/tree/0.15.0
The modification adds an optional `--title` command-line argument.

The emulator and its dependencies are downloaded on demand, not committed here.
Generated desktop packages include the emulator's corresponding source,
locked dependency sources, license notices, and build instructions in ThirdParty.
Mac packages include the exact patched source and the patch. Windows packages
use the unmodified official emulator executable.

Each game's code and assets retain their own licenses. The packer does not
include game source or assets in this repository. It does include the supplied
compiled ROM and its assets in the generated downloads.

This tool was extracted and generalized from MINECOM's packaging tools with
AI assistance. It is an independent community tool, not an official Firefly Zero
release or an upstream endorsement.
