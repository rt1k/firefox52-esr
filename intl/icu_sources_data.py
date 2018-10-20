#!/usr/bin/env python
#
# Any copyright is dedicated to the Public Domain.
# http://creativecommons.org/publicdomain/zero/1.0/
#
# Generate SOURCES in sources.mozbuild files from ICU's Makefile.in
# files, and also build a standalone copy of ICU using its build
# system to generate a new copy of the in-tree ICU data file.
#
# This script expects to be run from `update-icu.sh` after the in-tree
# copy of ICU has been updated.

from __future__ import print_function

import glob
import os
import shutil
import subprocess
import sys
import tempfile

from mozpack import path as mozpath


def find_source_file(dir, filename):
    base = os.path.splitext(filename)[0]
    for ext in ('.cpp', '.c'):
        f = mozpath.join(dir, base + ext)
        if os.path.isfile(f):
            return f
    raise Exception("Couldn't find source file for: %s" % filename)


def get_sources_from_makefile(makefile):
    import pymake.parser
    from pymake.parserdata import SetVariable
    srcdir = os.path.dirname(makefile)
    for statement in pymake.parser.parsefile(makefile):
        if (isinstance(statement, SetVariable) and
                statement.vnameexp.is_static_string and
                statement.vnameexp.s == 'OBJECTS'):
            return sorted((find_source_file(srcdir, s)
                           for s in statement.value.split()),
                          key=lambda x: x.lower())


def list_headers(path):
    result = []
    for name in os.listdir(path):
        f = mozpath.join(path, name)
        if os.path.isfile(f):
            result.append(f)
    return sorted(result, key=lambda x: x.lower())


def write_sources(mozbuild, sources, headers):
    with open(mozbuild, 'wb') as f:
        f.write('# THIS FILE IS GENERATED BY /intl/icu_sources_data.py ' +
                'DO NOT EDIT\n' +
                'SOURCES += [\n')
        f.write(''.join("   '/%s',\n" % s for s in sources))
        f.write(']\n\n')
        f.write('EXPORTS.unicode += [\n')
        f.write(''.join("   '/%s',\n" % s for s in headers))
        f.write(']\n')


def update_sources(topsrcdir):
    print('Updating ICU sources lists...')
    sys.path.append(mozpath.join(topsrcdir, 'build/pymake'))
    for d in ['common', 'i18n']:
        base_path = mozpath.join(topsrcdir, 'intl/icu/source/%s' % d)
        makefile = mozpath.join(base_path, 'Makefile.in')
        mozbuild = mozpath.join(topsrcdir,
                                'config/external/icu/%s/sources.mozbuild' % d)
        sources = [mozpath.relpath(s, topsrcdir)
                   for s in get_sources_from_makefile(makefile)]
        headers = [mozpath.normsep(os.path.relpath(s, topsrcdir))
                   for s in list_headers(mozpath.join(base_path, 'unicode'))]
        write_sources(mozbuild, sources, headers)


def try_run(name, command, cwd=None, **kwargs):
    try:
        with tempfile.NamedTemporaryFile(prefix=name, delete=False) as f:
            subprocess.check_call(command, cwd=cwd, stdout=f,
                                stderr=subprocess.STDOUT, **kwargs)
    except subprocess.CalledProcessError:
        print('''Error running "{}" in directory {}
    See output in {}'''.format(' '.join(command), cwd, f.name),
            file=sys.stderr)
        return False
    else:
        os.unlink(f.name)
        return True


def get_data_file(data_dir):
    files = glob.glob(mozpath.join(data_dir, 'icudt*.dat'))
    return files[0] if files else None


def update_data_file(topsrcdir):
    objdir = tempfile.mkdtemp(prefix='icu-obj-')
    configure = mozpath.join(topsrcdir, 'intl/icu/source/configure')
    env = dict(os.environ)
    # bug 1262101 - these should be shared with the moz.build files
    env.update({
        'CPPFLAGS': ('-DU_NO_DEFAULT_INCLUDE_UTF_HEADERS=1 ' +
                     '-DUCONFIG_NO_LEGACY_CONVERSION ' +
                     '-DUCONFIG_NO_TRANSLITERATION ' +
                     '-DUCONFIG_NO_REGULAR_EXPRESSIONS ' +
                     '-DUCONFIG_NO_BREAK_ITERATION ' +
                     '-DU_CHARSET_IS_UTF8')
    })
    print('Running ICU configure...')
    if not try_run(
            'icu-configure',
            ['sh', configure,
             '--with-data-packaging=archive',
             '--enable-static',
             '--disable-shared',
             '--disable-extras',
             '--disable-icuio',
             '--disable-layout',
             '--disable-layoutex',
             '--disable-tests',
             '--disable-samples',
             '--disable-strict'],
            cwd=objdir,
            env=env):
        return False
    print('Running ICU make...')
    if not try_run('icu-make', ['make'], cwd=objdir):
        return False
    print('Copying ICU data file...')
    tree_data_path = mozpath.join(topsrcdir,
                                  'config/external/icu/data/')
    old_data_file = get_data_file(tree_data_path)
    if not old_data_file:
        print('Error: no ICU data file in %s' % tree_data_path,
              file=sys.stderr)
        return False
    new_data_file = get_data_file(mozpath.join(objdir, 'data/out'))
    if not new_data_file:
        print('Error: no ICU data in ICU objdir', file=sys.stderr)
        return False
    if os.path.basename(old_data_file) != os.path.basename(new_data_file):
        # Data file name has the major version number embedded.
        os.unlink(old_data_file)
    shutil.copy(new_data_file, tree_data_path)
    try:
        shutil.rmtree(objdir)
    except:
        print('Warning: failed to remove %s' % objdir, file=sys.stderr)
    return True


def main():
    if len(sys.argv) != 2:
        print('Usage: icu_sources_data.py <mozilla topsrcdir>',
              file=sys.stderr)
        sys.exit(1)

    topsrcdir = mozpath.abspath(sys.argv[1])
    update_sources(topsrcdir)
    if not update_data_file(topsrcdir):
        print('Error updating ICU data file', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()