#!/usr/bin/env python3

import subprocess
import unittest
from unittest import mock

import quibble.commands


class ExtSkinSubmoduleUpdateCommandTest(unittest.TestCase):

    def test_submodule_update_errors(self):
        c = quibble.commands.ExtSkinSubmoduleUpdateCommand('/tmp')

        with mock.patch('os.walk') as mock_walk:
            mock_walk.side_effect = self.walk_extensions
            with mock.patch('subprocess.check_call') as mock_check_call:
                # A git command failing aborts.
                mock_check_call.side_effect = subprocess.CalledProcessError(
                    1, 'git something')
                with self.assertRaises(subprocess.CalledProcessError):
                    c.execute()

                mock_check_call.assert_called_once_with(
                    ['git', 'submodule', 'foreach',
                        'git', 'clean', '-xdff', '-q'],
                    cwd='/tmp/extensions/VisualEditor')

    def test_submodule_update(self):
        c = quibble.commands.ExtSkinSubmoduleUpdateCommand('/tmp')

        with mock.patch('os.walk') as mock_walk:
            mock_walk.side_effect = self.walk_extensions
            with mock.patch('subprocess.check_call') as mock_check_call:
                c.execute()

                mock_check_call.assert_any_call(
                    ['git', 'submodule', 'foreach',
                        'git', 'clean', '-xdff', '-q'],
                    cwd='/tmp/extensions/VisualEditor')

                # There should only be three calls, if there are more then we
                # must have recursed into a sub-subdirectory.
                self.assertEquals(
                    3, mock_check_call.call_count,
                    "Stopped after the first level directory")

    @staticmethod
    def walk_extensions(path):
        if path.endswith('/extensions'):
            return [
                ('/tmp/extensions', ['VisualEditor'], []),
                ('/tmp/extensions/VisualEditor', ['includes'],
                    ['.gitmodules']),
            ]
        else:
            return []


class CreateComposerLocalTest(unittest.TestCase):

    def test_execute(self):
        c = quibble.commands.CreateComposerLocal(
            '/tmp',
            ['mediawiki/extensions/Wikibase', 'justinrainbow/jsonschema'])

        with mock.patch('json.dump') as mock_dump:
            c.execute()

            expected = {
                'extra': {
                    'merge-plugin': {
                        'include': ['extensions/Wikibase/composer.json']
                    }
                }
            }
            mock_dump.assert_called_with(expected, mock.ANY)


class ExtSkinComposerNpmTestTest(unittest.TestCase):

    @staticmethod
    def no_spawn_map(wrapper, tasks):
        '''Replace imap_unordered with sequential execution'''
        for task_def in tasks:
            yield wrapper(task_def)

    @mock.patch('multiprocessing.pool.Pool')
    @mock.patch('subprocess.check_call')
    @mock.patch('os.path.exists')
    def test_execute_all(self, mock_exists, mock_call, mock_pool):

        mock_exists.return_value = True
        mock_pool.return_value.__enter__.return_value\
            .imap_unordered.side_effect = self.no_spawn_map

        c = quibble.commands.ExtSkinComposerNpmTest('/tmp', True, True)
        c.execute()

        mock_call.assert_any_call(['composer', '--ansi', 'test'], cwd='/tmp')
        mock_call.assert_any_call(['npm', 'test'], cwd='/tmp')

    @mock.patch('multiprocessing.pool.Pool')
    @mock.patch('subprocess.check_call')
    @mock.patch('os.path.exists')
    def test_execute_none(self, mock_exists, mock_call, mock_pool):

        mock_exists.return_value = False
        mock_pool.return_value.__enter__.return_value\
            .imap_unordered.side_effect = self.no_spawn_map

        c = quibble.commands.ExtSkinComposerNpmTest('/tmp', True, True)
        c.execute()

        mock_call.assert_called_once_with(
            ['git', 'clean', '-xqdf'], cwd='/tmp')


class VendorComposerDependenciesTest(unittest.TestCase):

    @mock.patch('builtins.open', mock.mock_open())
    @mock.patch('json.load')
    @mock.patch('subprocess.check_call')
    @mock.patch('quibble.util.copylog')
    def test_execute(self, mock_copylog, mock_check_call, mock_load):
        c = quibble.commands.VendorComposerDependencies('/tmp', '/log')

        mock_load.return_value = {
            'require-dev': {
                'justinrainbow/jsonschema': '^1.2.3',
            }
        }

        c.execute()

        mock_check_call.assert_has_calls(
            [mock.call(['composer', 'require', '--dev', '--ansi',
                        '--no-progress', '--prefer-dist', '-v',
                        'justinrainbow/jsonschema=^1.2.3'],
                       cwd='/tmp/vendor')])


class InstallMediaWikiTest(unittest.TestCase):

    @mock.patch('builtins.open', mock.mock_open())
    @mock.patch('quibble.util.copylog')
    @mock.patch('subprocess.check_call')
    @mock.patch('quibble.backend.getDBClass')
    @mock.patch('quibble.mediawiki.maintenance.install')
    @mock.patch('quibble.mediawiki.maintenance.update')
    @mock.patch('quibble.mediawiki.maintenance.rebuildLocalisationCache')
    def test_execute(self, mock_rebuild_l10n, mock_update, mock_install_script,
                     mock_db_factory, mock_check_call, mock_copylog):
        c = quibble.commands.InstallMediaWiki(
            '/tmp', 'mysql', '/db', '/dump', '/log', True)

        db = mock.MagicMock(
            dbname='testwiki',
            user='USER',
            password='PASS',
            dbserver='SERVER')
        mock_db_factory.return_value = mock.MagicMock(return_value=db)

        # TODO: Assert that localsettings is edited correctly.

        c.execute()

        mock_install_script.assert_called_once_with(
            args=['--scriptpath=', '--dbtype=mysql', '--dbname=testwiki',
                  '--dbuser=USER', '--dbpass=PASS', '--dbserver=SERVER'],
            mwdir='/tmp')

        mock_update.assert_called_once_with(
            args=['--skip-external-dependencies'],
            mwdir='/tmp')
