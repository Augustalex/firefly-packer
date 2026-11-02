# firefly-packer

Turn an exported Firefly Zero ROM into a Windows download and a universal macOS
app. Players get the game and emulator together, with a launcher that opens the
game directly and keeps saves outside the download folder.

- Windows x64 ZIP with the official emulator and a batch launcher.
- macOS 11+ app supporting Apple Silicon and Intel, with an optional custom icon.
- Optional Developer ID signing, Apple notarization, and ticket stapling.
- Original ROM ZIP, package checksums, and emulator source/license notices.

## Requirements

The Python script uses the standard library. Install Python 3.12+, curl, Git,
Cargo, and the Firefly CLI (`firefly_cli`, tested with 0.20.0). Start with an
exported ROM ZIP; this tool does not compile your game or require AssemblyScript.

Building the Mac package requires macOS, Xcode command line tools, and both Rust
targets. The tested toolchain is pinned:

```sh
rustup toolchain install 1.98.1 --profile minimal
rustup target add --toolchain 1.98.1 aarch64-apple-darwin x86_64-apple-darwin
```

Windows-only packaging can be run on macOS or Linux without Xcode or the Mac
targets. A native Windows packaging host has not been tested. The generated
Windows executable requires the Microsoft Visual C++ x64 runtime on the player's
computer. The launcher checks for it and provides Microsoft's download link.

## Package a game

```sh
cp firefly-packer.example.toml firefly-packer.toml
# Edit the config and point rom at your exported game ZIP.
python3 firefly_packer.py --config firefly-packer.toml
```

Set `app_id` to the ROM's `author_id.app_id`. Set the name, slug, version, build
number, and controls for your game. An optional `.icns` file supplies the Mac app
icon. Relative ROM/icon paths resolve from the config's directory.

For Windows only:

```sh
python3 firefly_packer.py --target windows --config firefly-packer.toml
```

Outputs in `dist/`:

```text
my-game.zip
my-game-windows.zip
my-game-macos.zip
my-game-manifest.json
```

Use `--output PATH` and `--cache PATH` to override output and cache locations.
The first build downloads and vendors the emulator dependencies, so it needs
network access, time, and several GB of free disk. Subsequent builds reuse the
cache. Emulator version 0.15.0 and upstream archive SHA-256 hashes are pinned in
`firefly_packer.py`. Change the version, hashes, and patch together when updating.

Windows players extract the whole ZIP and open `Play my-game.bat`. Mac players
open `My Game.app`. Both archives contain an itch app launch action and a
README containing the configured keyboard controls.

## How it works

The script imports your ROM into a temporary Firefly filesystem to obtain clean
initial config and stats. It packages only the ROM and fresh defaults, not your
developer save data. Launchers preserve existing config/saves and refresh the ROM.
Saves are stored in `%LOCALAPPDATA%\my-game` on Windows and
`~/Library/Application Support/my-game` on macOS. Choose a unique, stable slug
and retain it between releases to preserve the save location. If migrating an
existing release, set `data_folder` to its existing folder name (for example,
`MyGame`) to preserve saves independently of the output ZIP slug.

For Windows, the official x64 emulator binary is downloaded and hash-checked.
For macOS, the emulator source is hash-checked, patched to accept `--title`, and
built for `aarch64-apple-darwin` and `x86_64-apple-darwin`. Apple's `lipo -create`
combines these into a universal executable. The small Objective-C launcher is
also compiled for both architectures. No game source is converted to native code;
the bundled emulator runs the same WebAssembly ROM on both platforms.

## Sign and notarize the Mac app

Without a signing identity the app is ad hoc signed for local testing. That is
not an Apple-notarized distribution build.

For distribution, use your own installed Developer ID Application certificate:

```sh
export FIREFLY_PACKER_SIGN_IDENTITY='Developer ID Application: Your Company (TEAMID)'
python3 firefly_packer.py --config firefly-packer.toml --target macos
```

Signing uses hardened runtime and, for Developer ID signatures, a secure
timestamp. To also submit the signed app to Apple, use an existing notarytool
Keychain profile:

```sh
python3 firefly_packer.py --config firefly-packer.toml --target macos \
  --notarize-profile your-keychain-profile
```

This option uploads the app to Apple and waits for the result. After acceptance,
the script staples and validates the ticket, checks Gatekeeper, and repacks the
ZIP using `ditto` to preserve macOS metadata. If rejected, the command fails;
inspect Apple's submission log before distributing the output.

Certificates, private keys, passwords, and Apple account credentials do not belong
in this repository or config. Manage notarization credentials with Apple's
`xcrun notarytool store-credentials`. Rebuilds require fresh signing/notarization.
See [Apple's notarization documentation](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 firefly_packer.py --help
```

After building, extract the archives to a different folder. Verify ROM checksums,
launch the Mac app with isolated data, and check its architectures and signature:

```sh
lipo -archs 'My Game.app/Contents/MacOS/firefly-emulator'
codesign --verify --deep --strict 'My Game.app'
FIREFLY_PACKER_DATA_DIR=/tmp/firefly-packer-test \
  'My Game.app/Contents/MacOS/FireflyLauncher'
```

Also test the Windows download on a Windows computer, including one without the
Visual C++ runtime. Packaging on a Mac does not verify Windows execution.

## License

Original packer and launcher code: MIT. The emulator patch: GPL-3.0.
Generated packages retain the emulator and dependency source/license notices.
See [NOTICE.md](NOTICE.md). Your game's license is your own choice.
