"""Encapsulates each step of a job"""

from contextlib import ExitStack
import json
import logging
import os
import os.path
import pkg_resources
from quibble.gitchangedinhead import GitChangedInHead
from quibble.util import copylog, parallel_run
import quibble.zuul
import subprocess

log = logging.getLogger(__name__)
HTTP_PORT = 9412


class ZuulCloneCommand:
    def __init__(self, branch, cache_dir, project_branch, projects, workers,
                 workspace, zuul_branch, zuul_newrev, zuul_project, zuul_ref,
                 zuul_url):
        self.branch = branch
        self.cache_dir = cache_dir
        self.project_branch = project_branch
        self.projects = projects
        self.workers = workers
        self.workspace = workspace
        self.zuul_branch = zuul_branch
        self.zuul_newrev = zuul_newrev
        self.zuul_project = zuul_project
        self.zuul_ref = zuul_ref
        self.zuul_url = zuul_url

    def execute(self):
        quibble.zuul.clone(
            self.branch, self.cache_dir, self.project_branch, self.projects,
            self.workers, self.workspace, self.zuul_branch, self.zuul_newrev,
            self.zuul_project, self.zuul_ref, self.zuul_url)

    def __str__(self):
        pruned_params = {k: v for k, v in self.__dict__.items()
                         if v is not None and v != []}
        return "Zuul clone with parameters {}".format(
            json.dumps(pruned_params))


class ExtSkinSubmoduleUpdateCommand:
    def __init__(self, mw_install_path):
        self.mw_install_path = mw_install_path

    def execute(self):
        log.info('Updating git submodules of extensions and skins')

        cmds = [
            ['git', 'submodule', 'foreach', 'git', 'clean', '-xdff', '-q'],
            ['git', 'submodule', 'update', '--init', '--recursive'],
            ['git', 'submodule', 'status'],
        ]

        tops = [os.path.join(self.mw_install_path, top)
                for top in ['extensions', 'skins']]

        for top in tops:
            for dirpath, dirnames, filenames in os.walk(top):
                if dirpath not in tops:
                    # Only look at the first level
                    dirnames[:] = []
                if '.gitmodules' not in filenames:
                    continue

                for cmd in cmds:
                    try:
                        subprocess.check_call(cmd, cwd=dirpath)
                    except subprocess.CalledProcessError as e:
                        log.error(
                            "Failed to process git submodules for {}".format(
                                dirpath))
                        raise e

    def __str__(self):
        # TODO: Would be nicer to extract the directory crawl into a subroutine
        # and print the analysis here.
        return "Extension and skin submodule update under MediaWiki root {}"\
            .format(self.mw_install_path)


# Used to be bin/mw-create-composer-local.py
class CreateComposerLocal:
    def __init__(self, mw_install_path, dependencies):
        self.mw_install_path = mw_install_path
        self.dependencies = dependencies

    def execute(self):
        log.info('composer.local.json for merge plugin')
        extensions = [ext.strip()[len('mediawiki/'):] + '/composer.json'
                      for ext in self.dependencies
                      if ext.strip().startswith('mediawiki/extensions/')]
        out = {
            'extra': {
                'merge-plugin': {'include': extensions}
                }
            }
        composer_local = os.path.join(self.mw_install_path,
                                      'composer.local.json')
        with open(composer_local, 'w') as f:
            json.dump(out, f)
        log.info('Created composer.local.json')

    def __str__(self):
        return "Create composer.local.json with dependencies {}".format(
            self.dependencies)


class ExtSkinComposerNpmTest:
    def __init__(self, directory, composer, npm):
        self.directory = directory
        self.composer = composer
        self.npm = npm

    def execute(self):
        tasks = []
        if self.composer:
            tasks.append((self.run_extskin_composer, ))
        if self.npm:
            tasks.append((self.run_extskin_npm, ))

        # TODO: Split these tasks and move parallelism into calling logic.
        parallel_run(tasks)

        log.info('%s: git clean -xqdf' % self.directory)
        subprocess.check_call(['git', 'clean', '-xqdf'],
                              cwd=self.directory)

    def run_extskin_composer(self):
        project_name = os.path.basename(self.directory)

        if not os.path.exists(os.path.join(self.directory, 'composer.json')):
            log.warning("%s lacks a composer.json" % project_name)
            return

        log.info('Running "composer test" for %s' % project_name)
        cmds = [
            ['composer', '--ansi', 'validate', '--no-check-publish'],
            ['composer', '--ansi', 'install', '--no-progress',
             '--prefer-dist', '--profile', '-v'],
            ['composer', '--ansi', 'test'],
        ]
        for cmd in cmds:
            subprocess.check_call(cmd, cwd=self.directory)

    def run_extskin_npm(self):
        project_name = os.path.basename(self.directory)

        # FIXME: copy paste is terrible
        # TODO: Detect test existence in an earlier phase.
        if not os.path.exists(os.path.join(self.directory, 'package.json')):
            log.warning("%s lacks a package.json" % project_name)
            return

        log.info('Running "npm test" for %s' % project_name)
        cmds = [
            ['npm', 'prune'],
            ['npm', 'install', '--no-progress'],
            ['npm', 'test'],
        ]
        for cmd in cmds:
            subprocess.check_call(cmd, cwd=self.directory)

    def __str__(self):
        tests = []
        if self.composer:
            tests.append("composer")
        if self.npm:
            tests.append("npm")
        return "Extension and skin tests: {}".format(", ".join(tests))


class CoreNpmComposerTest:
    def __init__(self, mw_install_path, composer, npm):
        self.mw_install_path = mw_install_path
        self.composer = composer
        self.npm = npm

    def execute(self):
        tasks = []
        if self.composer:
            tasks.append((self.run_composer_test, ))
        if self.npm:
            tasks.append((self.run_npm_test, ))

        # TODO: Split these tasks and move parallelism into calling logic.
        parallel_run(tasks)

    def run_composer_test(self):
        files = []
        changed = GitChangedInHead([], cwd=self.mw_install_path).changedFiles()
        if 'composer.json' in changed or '.phpcs.xml' in changed:
            log.info(
                'composer.json or .phpcs.xml changed: linting "."')
            # '.' is passed to composer lint which then pass it
            # to parallel-lint and phpcs
            files = ['.']
        else:
            files = GitChangedInHead(
                ['php', 'php5', 'inc', 'sample'],
                cwd=self.mw_install_path
            ).changedFiles()

        if not files:
            log.info('Skipping composer test (unneeded)')
        else:
            log.info("Running composer test")

            env = {'COMPOSER_PROCESS_TIMEOUT': '900'}
            env.update(os.environ)

            composer_test_cmd = ['composer', 'test']
            composer_test_cmd.extend(files)
            subprocess.check_call(
                composer_test_cmd, cwd=self.mw_install_path, env=env)

    def run_npm_test(self):
        log.info("Running npm test")
        subprocess.check_call(['npm', 'test'], cwd=self.mw_install_path)

    def __str__(self):
        tests = []
        if self.composer:
            tests.append("composer")
        if self.npm:
            tests.append("npm")
        return "Run tests in mediawiki/core: {}".format(", ".join(tests))


class NativeComposerDependencies:
    def __init__(self, mw_install_path):
        self.mw_install_path = mw_install_path

    def execute(self):
        log.info('Running "composer update" for mediawiki/core')
        cmd = ['composer', 'update',
               '--ansi', '--no-progress', '--prefer-dist',
               '--profile', '-v',
               ]
        subprocess.check_call(cmd, cwd=self.mw_install_path)

    def __str__(self):
        return "Run composer update for mediawiki/core"


class VendorComposerDependencies:
    def __init__(self, mw_install_path, log_dir):
        self.mw_install_path = mw_install_path
        self.log_dir = log_dir

    def execute(self):
        log.info('vendor.git used. '
                 'Requiring composer dev dependencies')
        mw_composer_json = os.path.join(self.mw_install_path, 'composer.json')
        vendor_dir = os.path.join(self.mw_install_path, 'vendor')
        with open(mw_composer_json, 'r') as f:
            composer = json.load(f)

        reqs = ['='.join([dependency, version])
                for dependency, version in composer['require-dev'].items()]

        log.debug('composer require %s' % ' '.join(reqs))
        composer_require = ['composer', 'require', '--dev', '--ansi',
                            '--no-progress', '--prefer-dist', '-v']
        composer_require.extend(reqs)

        subprocess.check_call(composer_require, cwd=vendor_dir)

        # Point composer-merge-plugin to mediawiki/core.
        # That let us easily merge autoload-dev section and thus complete
        # the autoloader.
        # T158674
        subprocess.check_call([
            'composer', 'config',
            'extra.merge-plugin.include', mw_composer_json],
            cwd=vendor_dir)

        # FIXME integration/composer used to be outdated and broke the
        # autoloader. Since composer 1.0.0-alpha11 the following might not
        # be needed anymore.
        subprocess.check_call([
            'composer', 'dump-autoload', '--optimize'],
            cwd=vendor_dir)

        copylog(mw_composer_json,
                os.path.join(self.log_dir, 'composer.core.json.txt'))
        copylog(os.path.join(vendor_dir, 'composer.json'),
                os.path.join(self.log_dir, 'composer.vendor.json.txt'))
        copylog(os.path.join(vendor_dir, 'composer/autoload_files.php'),
                os.path.join(self.log_dir, 'composer.autoload_files.php.txt'))

    def __str__(self):
        return "Install composer dev-requires for vendor.git"


class NpmInstall:
    def __init__(self, directory):
        self.directory = directory

    def execute(self):
        subprocess.check_call(['npm', 'prune'], cwd=self.directory)
        subprocess.check_call(['npm', 'install'], cwd=self.directory)

    def __str__(self):
        return "npm install in {}".format(self.directory)


class InstallMediaWiki:

    db_backend = None

    def __init__(self, mw_install_path, db_engine, db_dir, dump_dir,
                 log_dir, use_vendor):
        self.mw_install_path = mw_install_path
        self.db_engine = db_engine
        self.db_dir = db_dir
        self.dump_dir = dump_dir
        self.log_dir = log_dir
        self.use_vendor = use_vendor

    def execute(self):
        dbclass = quibble.backend.getDBClass(engine=self.db_engine)
        db = dbclass(base_dir=self.db_dir, dump_dir=self.dump_dir)
        # hold a reference to prevent gc
        InstallMediaWiki.db_backend = db
        db.start()

        # TODO: Better if we can calculate the install args before
        # instantiating the database.
        install_args = [
            '--scriptpath=',
            '--dbtype=%s' % self.db_engine,
            '--dbname=%s' % db.dbname,
        ]
        if self.db_engine == 'sqlite':
            install_args.extend([
                '--dbpath=%s' % db.rootdir,
            ])
        elif self.db_engine in ('mysql', 'postgres'):
            install_args.extend([
                '--dbuser=%s' % db.user,
                '--dbpass=%s' % db.password,
                '--dbserver=%s' % db.dbserver,
            ])
        else:
            raise Exception('Unsupported database: %s' % self.db_engine)

        quibble.mediawiki.maintenance.install(
            args=install_args,
            mwdir=self.mw_install_path
        )

        localsettings = os.path.join(self.mw_install_path, 'LocalSettings.php')
        # Prepend our custom configuration snippets
        with open(localsettings, 'r+') as lf:
            quibblesettings = pkg_resources.resource_filename(
                __name__, 'mediawiki/local_settings.php')
            with open(quibblesettings) as qf:
                quibble_conf = qf.read()

            installed_conf = lf.read()
            lf.seek(0, 0)
            lf.write(quibble_conf + '\n?>' + installed_conf)
        copylog(localsettings,
                os.path.join(self.log_dir, 'LocalSettings.php'))
        subprocess.check_call(['php', '-l', localsettings])

        update_args = []
        if self.use_vendor:
            # When trying to update a library in mediawiki/core and
            # mediawiki/vendor, a circular dependency is produced as both
            # patches depend upon each other.
            #
            # All non-mediawiki/vendor jobs will skip checking for matching
            # versions and continue "at their own risk". mediawiki/vendor will
            # still check versions to make sure it stays in sync with MediaWiki
            # core.
            #
            # T88211
            log.info('mediawiki/vendor used. '
                     'Skipping external dependencies')
            update_args.append('--skip-external-dependencies')

        quibble.mediawiki.maintenance.update(
            args=update_args,
            mwdir=self.mw_install_path
        )
        quibble.mediawiki.maintenance.rebuildLocalisationCache(
            lang=['en'], mwdir=self.mw_install_path)

    def __str__(self):
        return "Install MediaWiki, db={} db_dir={} vendor={}".format(
            self.db_engine, self.db_dir, self.use_vendor)


class AbstractPhpUnit:
    def run_phpunit(self, group=[], exclude_group=[]):
        log.info(self)

        always_excluded = ['Broken', 'ParserFuzz', 'Stub']

        cmd = ['php', 'tests/phpunit/phpunit.php', '--debug-tests']
        if self.testsuite:
            cmd.extend(['--testsuite', self.testsuite])

        if group:
            cmd.extend(['--group', ','.join(group)])

        cmd.extend(['--exclude-group',
                    ','.join(always_excluded + exclude_group)])

        if self.junit_file:
            cmd.extend(['--log-junit', self.junit_file])
        log.info(' '.join(cmd))

        phpunit_env = {}
        phpunit_env.update(os.environ)
        phpunit_env.update({'LANG': 'C.UTF-8'})

        subprocess.check_call(cmd, cwd=self.mw_install_path, env=phpunit_env)


class PhpUnitDatabaseless(AbstractPhpUnit):
    def __init__(self, mw_install_path, testsuite, log_dir):
        self.mw_install_path = mw_install_path
        self.testsuite = testsuite
        self.log_dir = log_dir
        self.junit_file = os.path.join(self.log_dir, 'junit-dbless.xml')

    def execute(self):
        # XXX might want to run the triggered extension first then the
        # other tests.
        # XXX some mediawiki/core smoke PHPunit tests should probably
        # be run as well.
        self.run_phpunit(exclude_group=['Database'])

    def __str__(self):
        return "PHPUnit {} suite (without database)".format(
            self.testsuite or 'default')


class PhpUnitDatabase(AbstractPhpUnit):
    def __init__(self, mw_install_path, testsuite, log_dir):
        self.mw_install_path = mw_install_path
        self.testsuite = testsuite
        self.log_dir = log_dir
        self.junit_file = os.path.join(self.log_dir, 'junit-db.xml')

    def execute(self):
        self.run_phpunit(group=['Database'])

    def __str__(self):
        return "PHPUnit {} suite (with database)".format(
            self.testsuite or 'default')


class BrowserTests:
    def __init__(self, mw_install_path, qunit, selenium, display):
        self.mw_install_path = mw_install_path
        self.qunit = qunit
        # FIXME: find a nice way to analyze whether we're actually running
        # qunit or selenium before creating the command.
        self.selenium = selenium
        self.display = display

    def execute(self):
        with quibble.backend.DevWebServer(
                mwdir=self.mw_install_path,
                port=HTTP_PORT):
            if self.qunit:
                self.run_qunit()

            # Webdriver.io Selenium tests available since 1.29
            if self.selenium and \
                    os.path.exists(os.path.join(
                        self.mw_install_path, 'tests/selenium')):
                with ExitStack() as stack:
                    if not self.display:
                        self.display = ':94'  # XXX racy when run concurrently!
                        log.info("No DISPLAY, using Xvfb.")
                        stack.enter_context(
                            quibble.backend.Xvfb(display=self.display))

                    with quibble.backend.ChromeWebDriver(display=self.display):
                        self.run_webdriver()

    def run_qunit(self):
        karma_env = {
             'CHROME_BIN': '/usr/bin/chromium',
             'MW_SERVER': 'http://127.0.0.1:%s' % HTTP_PORT,
             'MW_SCRIPT_PATH': '/',
             'FORCE_COLOR': '1',  # for 'supports-color'
             }
        karma_env.update(os.environ)
        karma_env.update({'CHROMIUM_FLAGS': quibble.chromium_flags()})

        subprocess.check_call(
            ['./node_modules/.bin/grunt', 'qunit'],
            cwd=self.mw_install_path,
            env=karma_env,
        )

    def run_webdriver(self):
        webdriver_env = {}
        webdriver_env.update(os.environ)
        webdriver_env.update({
            'MW_SERVER': 'http://127.0.0.1:%s' % HTTP_PORT,
            'MW_SCRIPT_PATH': '/',
            'FORCE_COLOR': '1',  # for 'supports-color'
            'MEDIAWIKI_USER': 'WikiAdmin',
            'MEDIAWIKI_PASSWORD': 'testwikijenkinspass',
            'DISPLAY': self.display,
        })

        subprocess.check_call(
            ['npm', 'run', 'selenium-test'],
            cwd=self.mw_install_path,
            env=webdriver_env)

    def __str__(self):
        tests = []
        if self.qunit:
            tests.append("qunit")
        if self.selenium:
            tests.append("selenium (maybe)")

        return "Browser tests in {}: {} using DISPLAY={}".format(
            self.mw_install_path, ", ".join(tests), self.display or "Xvfb")


class UserCommands:
    def __init__(self, mw_install_path, commands):
        self.mw_install_path = mw_install_path
        self.commands = commands

    def execute(self):
        log.info('User commands')
        with quibble.backend.DevWebServer(
                mwdir=self.mw_install_path,
                port=HTTP_PORT):
            log.info('working directory: %s' % self.mw_install_path)

            for cmd in self.commands:
                log.info(cmd)
                subprocess.check_call(
                    cmd, shell=True, cwd=self.mw_install_path)

    def __str__(self):
        return "User commands: {}".format(", ".join(self.commands))
