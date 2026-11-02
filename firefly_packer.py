"""Package an exported Firefly Zero ROM for Windows and universal macOS."""

import argparse
from dataclasses import dataclass
import platform
import re
import sys
import hashlib
import json
import os
import plistlib
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache"
OUTPUT = ROOT / "dist"
VERSION = "0.15.0"
RUST_VERSION = "1.98.1"
REPOSITORY = "https://github.com/firefly-zero/firefly-emulator"
SOURCE_HASH = "db636ec7240a83083c2c8ea78abe26b9a8640969c683b28a96bed3b859d19e1f"
ASSETS = {
    "aarch64-apple-darwin": "f403e79b7e6fdb05b168f25a1d8d9cca4fe5eecd313d92f50ffbd422ab90e562",
    "x86_64-apple-darwin": "8ed09573a339c9215c3dd20b91eaa580f54674d9e2b3b635c6cad4b9f44f82c1",
    "x86_64-pc-windows-msvc": "0894123e01024bee6f0892e913992853a9fd84a56e1a622f407a248ba63c839c",
}


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def download(url, path, digest):
    if not path.exists():
        partial = path.with_suffix(path.suffix + ".partial")
        run("curl", "-fsSL", "--retry", "3", url, "-o", partial)
        partial.replace(path)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest:
        raise ValueError(f"Checksum mismatch for {path.name}: {actual}")


def emulator(target):
    name = f"firefly-emulator-{target}.tgz"
    archive = CACHE / name
    download(f"{REPOSITORY}/releases/download/{VERSION}/{name}", archive, ASSETS[target])
    destination = CACHE / name.removesuffix(".tgz")
    destination.mkdir(exist_ok=True)
    with tarfile.open(archive) as source:
        source.extractall(destination, filter="data")
    suffix = ".exe" if "windows" in target else ""
    return target, destination / f"firefly-emulator{suffix}"


def corresponding_source():
    archive = CACHE / f"firefly-emulator-{VERSION}.tar.gz"
    download(f"https://codeload.github.com/firefly-zero/firefly-emulator/tar.gz/refs/tags/{VERSION}", archive, SOURCE_HASH)
    source = CACHE / f"firefly-emulator-{VERSION}"
    if not source.exists():
        with tarfile.open(archive) as contents:
            contents.extractall(CACHE, filter="data")
    locked = tomllib.loads((source / "Cargo.lock").read_text())["package"]
    expected = [p for p in locked if "source" in p]
    vendor = source / "vendor"
    if any(not (vendor / f"{p['name']}-{p['version']}" / ".cargo-checksum.json").exists() for p in expected):
        with (CACHE / "vendor.log").open("w") as log:
            run("cargo", "vendor", "--locked", "--versioned-dirs", "--manifest-path", source / "Cargo.toml", vendor,
                stdout=subprocess.DEVNULL, stderr=log)
    for package in expected:
        checksum = json.loads((vendor / f"{package['name']}-{package['version']}" / ".cargo-checksum.json").read_text())
        if checksum["package"] != package["checksum"]:
            raise ValueError(f"Vendored source checksum mismatch: {package['name']}")
    (source / ".cargo").mkdir(exist_ok=True)
    (source / ".cargo/config.toml").write_text(
        '[source.crates-io]\nreplace-with = "vendored-sources"\n\n'
        '[source.vendored-sources]\ndirectory = "vendor"\n')
    (source / "BUNDLE-SOURCE.txt").write_text(
        f"Source for the unmodified Firefly emulator {VERSION} included with the packaged game.\n"
        f"Upstream: {REPOSITORY}/tree/{VERSION}\n\n"
        "Includes Cargo.lock, upstream build scripts and all locked dependency sources.\n"
        "Install Rust 1.98.1 or a compatible newer toolchain and platform build tools.\n"
        "From this directory, build with:\n"
        "  cargo build --offline --locked --release --target x86_64-pc-windows-msvc\n"
        "or aarch64-apple-darwin / x86_64-apple-darwin on macOS.\n"
        "The Mac app combines both Mac executables using lipo.\n"
        "The game's source is not part of this emulator source archive.\n")
    kit = CACHE / f"firefly-emulator-{VERSION}-packer-source.tar.gz"
    if not kit.exists():
        print("Archiving emulator source and dependencies...", flush=True)
        with tarfile.open(kit, "w:gz", compresslevel=6) as contents:
            contents.add(source, arcname=source.name)
    return kit, source / "LICENSE", source


def mac_emulator(source):
    patch = ROOT / "patches/firefly-emulator-window-title.patch"
    digest = hashlib.sha256(patch.read_bytes()).hexdigest()[:12]
    work = CACHE / f"firefly-emulator-{VERSION}-packer-{digest}"
    if not (work / patch.name).exists():
        if work.exists():
            shutil.rmtree(work)  # Discard an interrupted generated source copy.
        shutil.copytree(source, work, ignore=lambda directory, names:
                        ["target"] if Path(directory) == source and "target" in names else [])
        run("git", "apply", "--check", patch, cwd=work)
        run("git", "apply", patch, cwd=work)
        (work / "BUNDLE-SOURCE.txt").write_text(
            f"Firefly emulator {VERSION}, modified for firefly-packer on 2026-11-02.\n"
            f"Upstream: {REPOSITORY}/tree/{VERSION}\n"
            "The included patch adds --title; the Mac launcher passes the configured game title.\n"
            "No game/runtime logic is changed. Patched source and locked dependencies are included.\n"
            f"Install Rust {RUST_VERSION}, both Mac targets, and Apple's command line tools.\n"
            "Set SDKROOT to the path from xcrun --sdk macosx --show-sdk-path.\n"
            "Set MACOSX_DEPLOYMENT_TARGET=11.0. Build each target from this directory:\n"
            f"  cargo +{RUST_VERSION} build --offline --locked --release --target aarch64-apple-darwin\n"
            f"  cargo +{RUST_VERSION} build --offline --locked --release --target x86_64-apple-darwin\n"
            "Combine target/*/release/firefly-emulator using lipo -create.\n"
            "The game's source is not included.\n")
        shutil.copy2(patch, work / patch.name)
    kit = CACHE / f"{work.name}-source.tar.gz"
    if not kit.exists():
        partial = kit.with_suffix(kit.suffix + ".partial")
        with tarfile.open(partial, "w:gz", compresslevel=6) as archive:
            archive.add(work, arcname=work.name, filter=lambda item: None
                        if item.name == f"{work.name}/target" or
                        item.name.startswith(f"{work.name}/target/") else item)
        partial.replace(kit)
    sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
    environment = dict(os.environ, SDKROOT=sdk, MACOSX_DEPLOYMENT_TARGET="11.0",
                       CFLAGS=f"-isysroot {sdk}", CXXFLAGS=f"-isysroot {sdk}")
    binaries = {}
    for target in ["aarch64-apple-darwin", "x86_64-apple-darwin"]:
        print(f"Building Mac emulator with window title option: {target}", flush=True)
        log = CACHE / f"build-{target}.log"
        with log.open("w") as output:
            result = subprocess.run(["cargo", f"+{RUST_VERSION}", "build", "--offline", "--locked",
                                     "--release", "--target", target], cwd=work, env=environment,
                                    stdout=output, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"Mac emulator build failed. See {log}\n{log.read_text()[-6000:]}")
        binaries[target] = work / "target" / target / "release/firefly-emulator"
    return binaries, kit


def write(path, value, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    path.chmod(0o755 if executable else 0o644)


def sign_mac(path):
    identity = os.environ.get("FIREFLY_PACKER_SIGN_IDENTITY", "-")
    timestamp = "--timestamp=none" if identity == "-" else "--timestamp"
    run("codesign", "--force", "--sign", identity, "--options", "runtime", timestamp, path)


def notices(destination, source_kit, license_file, modified=False):
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(license_file, destination / "Firefly-GPL-3.0.txt")
    shutil.copy2(ROOT / "LICENSE", destination / "Firefly-Packer-MIT.txt")
    shutil.copy2(source_kit, destination / source_kit.name)
    modification = ("Modified for firefly-packer on 2026-11-02: adds the --title window title option.\n"
                    "The exact patched source and patch are included in the source archive.") if modified else "No emulator code is modified."
    write(destination / "NOTICE.txt", f"""Includes Firefly Zero emulator {VERSION}, licensed under GPL-3.0.
Copyright and license notices for its dependencies are included in the source archive.
Upstream: {REPOSITORY}/releases/tag/{VERSION}
Corresponding source: {source_kit.name}, included in this directory.
{modification}
The packaged game is a separate game loaded by this emulator.

""")


def zip_directory(directory, output):
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(directory.rglob("*")):
            archive.write(path, path.relative_to(directory))
    print(f"Created {output.name}: {output.stat().st_size / 1024 / 1024:.1f} MiB", flush=True)

@dataclass(frozen=True)
class Game:
    name: str
    slug: str
    app_id: str
    version: str
    build: str
    bundle_id: str
    rom: Path
    controls: str
    data_folder: str
    icon: Path | None = None
    scale: int = 4


def load_game(path):
    path = Path(path).resolve()
    config = tomllib.loads(path.read_text())
    allowed = {'name', 'slug', 'app_id', 'version', 'build', 'bundle_id', 'rom', 'controls', 'icon', 'scale', 'data_folder'}
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"Unknown config keys: {', '.join(sorted(unknown))}")
    for key in ('name', 'slug', 'app_id', 'version', 'rom'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"Config requires a nonempty {key!r} string")
    slug = config['slug']
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', slug):
        raise ValueError('slug must contain lowercase ASCII letters, digits, and hyphens')
    if not re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+', config['app_id']):
        raise ValueError('app_id must be author-id.app-id, as in firefly.toml')
    if any(c in config['name'] for c in '/\\\r\n\x00:') or config['name'] in ('.', '..'):
        raise ValueError('name must be a safe app filename, without slashes or control characters')
    if any(ord(c) < 32 for c in config['name']):
        raise ValueError('name must not contain control characters')
    bundle_id = config.get('bundle_id', f'games.firefly.{slug}')
    if not isinstance(bundle_id, str) or not re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', bundle_id):
        raise ValueError('bundle_id must be a reverse-domain identifier')
    scale = config.get('scale', 4)
    if type(scale) is not int or not 1 <= scale <= 8:
        raise ValueError('scale must be an integer from 1 to 8')
    build = str(config.get('build', '1'))
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,2}', build):
        raise ValueError('build must be a numeric macOS bundle build number')
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,2}', config['version']):
        raise ValueError('version must have one to three numeric components, such as 1.0.0')
    rom = (path.parent / config['rom']).resolve()
    if not rom.is_file() or not zipfile.is_zipfile(rom):
        raise ValueError(f'rom must point to an exported Firefly ROM ZIP: {rom}')
    icon = config.get('icon')
    if icon is not None:
        if not isinstance(icon, str):
            raise ValueError('icon must be a path string')
        icon = (path.parent / icon).resolve()
        if not icon.is_file() or icon.suffix.lower() != '.icns':
            raise ValueError('icon must point to an existing .icns file')
    data_folder = config.get('data_folder', slug)
    if not isinstance(data_folder, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*', data_folder):
        raise ValueError('data_folder must contain ASCII letters, digits, and hyphens')
    controls = config.get('controls', 'Arrow keys: directional input.\nA/S/Z/X: buttons.\nEnter: menu.\nEscape: close.\n')
    if not isinstance(controls, str):
        raise ValueError('controls must be a string')
    return Game(config['name'], slug, config['app_id'], config['version'], build,
                bundle_id, rom, controls, data_folder, icon, scale)


def windows_launcher(game):
    # Only validated ASCII slug/app_id and an integer enter shell commands.
    return f'''@echo off
setlocal
title {game.slug}
set "FIREFLY_DATA=%LOCALAPPDATA%\\{game.data_folder}"
if not exist "%SystemRoot%\\System32\\vcruntime140.dll" (
  echo This game needs the Microsoft Visual C++ x64 runtime.
  echo Download from https://aka.ms/vc14/vc_redist.x64.exe then try again.
  pause
  exit /b 1
)
robocopy "%~dp0initial-vfs" "%FIREFLY_DATA%" /E /XC /XN /XO /R:1 /W:1 /NFL /NDL /NJH /NJS >nul
if errorlevel 8 (
  echo Could not initialize game data.
  pause
  exit /b 1
)
robocopy "%~dp0roms" "%FIREFLY_DATA%\\roms" /E /R:1 /W:1 /NFL /NDL /NJH /NJS >nul
if errorlevel 8 (
  echo Could not prepare the game files.
  pause
  exit /b 1
)
"%~dp0firefly-emulator.exe" --vfs "%FIREFLY_DATA%" --id {game.app_id} --scale {game.scale}
if errorlevel 1 (
  echo The game could not start.
  pause
  exit /b 1
)
'''


def prepare_rom(game, stage):
    vfs = stage / 'vfs'
    run('firefly_cli', '--vfs', vfs, 'import', game.rom)
    author, app = game.app_id.split('.')
    roms = vfs / 'roms'
    if not (roms / author / app).is_dir():
        raise ValueError(f'ROM does not contain configured app_id {game.app_id}')
    initial = stage / 'initial-vfs'
    for relative in [Path('sys/config'), Path('data') / author / app / 'stats']:
        target = initial / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(vfs / relative, target)
    for relative in ['sys/priv', 'sys/pub', f'data/{author}/{app}/etc', f'data/{author}/{app}/shots']:
        (initial / relative).mkdir(parents=True, exist_ok=True)
    return roms, initial


def build_windows(game, stage, roms, initial, source_kit, license_file):
    destination = stage / 'windows'
    destination.mkdir()
    shutil.copy2(emulator('x86_64-pc-windows-msvc')[1], destination / 'firefly-emulator.exe')
    shutil.copytree(roms, destination / 'roms')
    shutil.copytree(initial, destination / 'initial-vfs')
    launcher = f'Play {game.slug}.bat'
    (destination / launcher).write_bytes(windows_launcher(game).replace('\n', '\r\n').encode('ascii'))
    write(destination / 'Install Microsoft Runtime.url', '[InternetShortcut]\nURL=https://aka.ms/vc14/vc_redist.x64.exe\n')
    write(destination / '.itch.toml', f'[[actions]]\nname = "Play"\npath = "{launcher}"\n')
    write(destination / 'README.txt', game.controls)
    notices(destination / 'ThirdParty', source_kit, license_file)
    output = OUTPUT / f'{game.slug}-windows.zip'
    zip_directory(destination, output)
    return output


def mac_zip(directory, output):
    # ditto preserves the macOS metadata and stapled notarization ticket.
    partial = output.with_suffix('.partial.zip')
    if partial.exists():
        partial.unlink()
    run('ditto', '-c', '-k', '--sequesterRsrc', directory, partial)
    partial.replace(output)
    return output


def notarize(app, archive, profile):
    identity = os.environ.get('FIREFLY_PACKER_SIGN_IDENTITY', '-')
    if identity == '-':
        raise ValueError('Notarization requires FIREFLY_PACKER_SIGN_IDENTITY set to a Developer ID Application identity')
    result = subprocess.run(['xcrun', 'notarytool', 'submit', str(archive), '--keychain-profile', profile,
                             '--wait', '--output-format', 'json'], capture_output=True, text=True, check=True)
    receipt = json.loads(result.stdout)
    print(f"Notarization: {receipt.get('status')} (submission {receipt.get('id')})", flush=True)
    if receipt.get('status') != 'Accepted':
        raise RuntimeError('Apple did not accept the app. Inspect the submission using xcrun notarytool log.')
    run('xcrun', 'stapler', 'staple', app)
    run('xcrun', 'stapler', 'validate', app)
    run('spctl', '--assess', '--type', 'execute', app)


def build_mac(game, stage, roms, initial, source, license_file, profile):
    binaries, source_kit = mac_emulator(source)
    destination = stage / 'macos'
    app = destination / f'{game.name}.app'
    contents = app / 'Contents'
    resources = contents / 'Resources'
    (contents / 'MacOS').mkdir(parents=True)
    shutil.copytree(roms, resources / 'roms')
    shutil.copytree(initial, resources / 'initial-vfs')
    emulator_binary = contents / 'MacOS/firefly-emulator'
    run('lipo', '-create', binaries['aarch64-apple-darwin'], binaries['x86_64-apple-darwin'], '-output', emulator_binary)
    emulator_binary.chmod(0o755)
    sign_mac(emulator_binary)
    sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
    run('xcrun', 'clang', '-isysroot', sdk, '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
        '-arch', 'arm64', '-arch', 'x86_64', '-mmacosx-version-min=11.0', '-framework', 'Cocoa',
        ROOT / 'native/mac-launcher.m', '-o', contents / 'MacOS/FireflyLauncher')
    info = {
        'CFBundleExecutable': 'FireflyLauncher', 'CFBundleIdentifier': game.bundle_id,
        'CFBundleName': game.name, 'CFBundleDisplayName': game.name, 'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': game.version, 'CFBundleVersion': game.build,
        'LSMinimumSystemVersion': '11.0', 'NSHighResolutionCapable': True,
        'FireflyAppID': game.app_id, 'FireflyDataFolder': game.data_folder, 'FireflyScale': game.scale,
    }
    if game.icon:
        shutil.copy2(game.icon, resources / 'Game.icns')
        info['CFBundleIconFile'] = 'Game.icns'
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    notices(resources / 'ThirdParty', source_kit, license_file, modified=True)
    sign_mac(app)
    run('codesign', '--verify', '--deep', '--strict', app)
    # JSON string quoting is compatible with TOML basic strings.
    write(destination / '.itch.toml', f'[[actions]]\nname = "Play"\npath = {json.dumps(app.name, ensure_ascii=False)}\n')
    write(destination / 'README.txt', game.controls)
    output = OUTPUT / f'{game.slug}-macos.zip'
    mac_zip(destination, output)
    if profile:
        notarize(app, output, profile)
        mac_zip(destination, output)
    return output


def main(argv=None):
    global CACHE, OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('firefly-packer.toml'))
    parser.add_argument('--target', choices=['windows', 'macos', 'all'], default='all')
    parser.add_argument('--output', type=Path, default=Path('dist'))
    parser.add_argument('--cache', type=Path, default=Path('.cache/firefly-packer'))
    parser.add_argument('--notarize-profile', help='Optional existing notarytool Keychain profile. Submits the signed app to Apple.')
    args = parser.parse_args(argv)
    game = load_game(args.config)
    wants_mac = args.target in ('all', 'macos')
    if wants_mac and platform.system() != 'Darwin':
        parser.error('macOS packaging requires a Mac with Xcode command line tools; use --target windows on other hosts')
    if args.notarize_profile and (not wants_mac or os.environ.get('FIREFLY_PACKER_SIGN_IDENTITY', '-') == '-'):
        parser.error('--notarize-profile requires a macOS target and FIREFLY_PACKER_SIGN_IDENTITY')
    CACHE = args.cache.resolve()
    OUTPUT = args.output.resolve()
    CACHE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_kit, license_file, source = corresponding_source()
    outputs = []
    with tempfile.TemporaryDirectory(prefix='firefly-packer-') as temporary:
        stage = Path(temporary)
        roms, initial = prepare_rom(game, stage)
        if args.target in ('all', 'windows'):
            outputs.append(build_windows(game, stage, roms, initial, source_kit, license_file))
        if wants_mac:
            outputs.append(build_mac(game, stage, roms, initial, source, license_file, args.notarize_profile))
    rom_output = OUTPUT / f'{game.slug}.zip'
    if rom_output != game.rom:
        shutil.copy2(game.rom, rom_output)
    outputs.append(rom_output)
    manifest = {'app_id': game.app_id, 'version': game.version, 'build': game.build,
                'emulator_version': VERSION, 'macos_notarized': bool(args.notarize_profile),
                'packages': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in outputs}}
    write(OUTPUT / f'{game.slug}-manifest.json', json.dumps(manifest, indent=2) + '\n')
    print(f'Packages ready in {OUTPUT}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError) as error:
        print(f'firefly-packer: {error}', file=sys.stderr)
        sys.exit(1)
