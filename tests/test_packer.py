import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import firefly_packer as packer


class PackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom = self.root / 'game.zip'
        with zipfile.ZipFile(self.rom, 'w') as archive:
            archive.writestr('_bin', b'\0asm')
        self.config = self.root / 'config.toml'

    def game(self, **overrides):
        config = dict(name='Test Game', slug='test-game', app_id='tester.game',
                      version='1.2.3', rom='game.zip')
        config.update(overrides)
        self.config.write_text('\n'.join(f'{key} = {json.dumps(value)}' for key, value in config.items()))
        return packer.load_game(self.config)

    def test_relative_paths_resolve_from_config(self):
        self.assertEqual(self.game().rom, self.rom.resolve())

    def test_rejects_unsafe_slug_and_app_id(self):
        for field, values in {'slug': ['../game', 'game&calc', '%PATH%', ''],
                              'app_id': ['tester.game&calc', '../game', 'no-author']}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.game(**{field: value})

    def test_migrated_save_folder(self):
        game = self.game(data_folder='ExistingGame')
        self.assertEqual(game.data_folder, 'ExistingGame')
        self.assertIn(r'%LOCALAPPDATA%\ExistingGame', packer.windows_launcher(game))
        with self.assertRaises(ValueError):
            self.game(data_folder='../escape')

    def test_rejects_invalid_mac_metadata(self):
        for key, value in [('name', '../Game'), ('name', 'Game\nFake'), ('version', '1.0-beta'),
                           ('build', '-1'), ('bundle_id', 'single'), ('scale', 0), ('scale', True)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.game(**{key: value})

    def test_rejects_unknown_config_and_missing_inputs(self):
        for override in ({'password': 'not-allowed'}, {'rom': 'missing.zip'}, {'icon': 'missing.icns'}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.game(**override)

    def test_windows_archive_contains_rom_and_notices(self):
        game = self.game(controls='Arrows: move.\n')
        roms = self.root / 'roms'
        (roms / 'tester/game').mkdir(parents=True)
        (roms / 'tester/game/_bin').write_bytes(b'\0asm')
        initial = self.root / 'initial'
        (initial / 'sys').mkdir(parents=True)
        (initial / 'sys/config').write_bytes(b'config')
        binary = self.root / 'emulator.exe'
        binary.write_bytes(b'fixture')
        source = self.root / 'emulator-source.tar.gz'
        source.write_bytes(b'fixture source archive')
        license_file = self.root / 'GPL.txt'
        license_file.write_text('fixture license')
        out = self.root / 'out'
        out.mkdir()
        stage = self.root / 'stage'
        stage.mkdir()
        with patch.object(packer, 'OUTPUT', out), patch.object(packer, 'emulator', return_value=('win', binary)):
            archive = packer.build_windows(game, stage, roms, initial, source, license_file)
        with zipfile.ZipFile(archive) as contents:
            self.assertEqual(contents.read('roms/tester/game/_bin'), b'\0asm')
            self.assertEqual(contents.read('README.txt'), b'Arrows: move.\n')
            launcher = contents.read('Play test-game.bat')
            self.assertIn(b'--id tester.game --scale 4', launcher)
            self.assertNotIn(b'\n', launcher.replace(b'\r\n', b''))
            self.assertIn('ThirdParty/Firefly-Packer-MIT.txt', contents.namelist())
            self.assertIn('ThirdParty/emulator-source.tar.gz', contents.namelist())
            self.assertIn('/XC /XN /XO', launcher.decode())

    def test_prepare_rom_excludes_private_data(self):
        game = self.game()
        def fake_import(*args):
            vfs = self.root / 'vfs'
            for relative in ['roms/tester/game/_bin', 'sys/config', 'data/tester/game/stats',
                             'data/tester/game/save', 'sys/secret']:
                path = vfs / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
        with patch.object(packer, 'run', side_effect=fake_import):
            roms, initial = packer.prepare_rom(game, self.root)
        self.assertTrue((roms / 'tester/game/_bin').exists())
        self.assertTrue((initial / 'data/tester/game/stats').exists())
        self.assertFalse((initial / 'data/tester/game/save').exists())
        self.assertFalse((initial / 'sys/secret').exists())

    def test_wrong_app_id_fails_before_packaging(self):
        with patch.object(packer, 'run'), self.assertRaisesRegex(ValueError, 'app_id'):
            packer.prepare_rom(self.game(), self.root)

    def test_notarization_requires_developer_identity(self):
        with patch.dict('os.environ', {}, clear=True), self.assertRaises(ValueError):
            packer.notarize(self.root / 'Game.app', self.rom, 'profile')


if __name__ == '__main__':
    unittest.main()
