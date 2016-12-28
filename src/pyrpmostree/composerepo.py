#!/usr/bin/env python
# Copyright (C) 2015 Colin Walters <walters@verbum.org>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.

import logging
import os
import json
import subprocess
import collections
import sys
from StringIO import StringIO

from gi.repository import GLib, Gio, OSTree

PackageChange = collections.namedtuple('PackageChange', ['frompkg', 'topkg'])

class RpmOstreeComposeRepo(object):
    """Class with various utility functions for doing compose/rel-eng
    operations.
    """

    def __init__(self, repopath):
        self.repopath = repopath
        self.repo = OSTree.Repo.new(Gio.File.new_for_path(self.repopath))
        self.repo.open(None)

    def delete_commits_with_key(self, ref, key):
        """Delete any commits that have @key as a detached metadata string.
        This is useful before doing a staging commit to ensure one is
        not shipping intermediate history.
        """

        # Note we require at least one 
        [_,rev] = self.repo.resolve_rev(ref, True)
        if rev is None:
            logging.info("No previous commit")
            return

        commit = None
        iter_rev = rev
        while True:
            _,commit = self.repo.load_variant(OSTree.ObjectType.COMMIT, iter_rev)
            _,metadata = self.repo.read_commit_detached_metadata(iter_rev, None)
            if (metadata is not None and metadata.unpack().get(key)):
                iter_rev = OSTree.commit_get_parent(commit)
                if iter_rev is None:
                    logging.error("Found a staging commit but no parent?")
                # skip this commit
                continue   
            else:
                break

        if iter_rev != rev:
            # We have commits to delete
            
            logging.info("Resetting {0} to {1}".format(ref, iter_rev))
            self.repo.set_ref_immediate(None, ref, iter_rev, None)
            
            # Now do a prune
            _,nobjs,npruned,objsize = self.repo.prune(OSTree.RepoPruneFlags.REFS_ONLY, -1, None)
            if npruned == 0:
                print "No unreachable objects"
            else:
                fmtsize = GLib.format_size_full(objsize, 0)
                logging.info("Deleted {0} objects, {1} freed".format(npruned, fmtsize))
        else:
            logging.info("No staging commits to prune")

    def pkgdiff(self, from_ref, to_ref):
        """Perform a package-level diff between two commits, returning a
        3-tuple (CHANGED, ADDED, REMOVED) where ADDED and REMOVED are simple
        lists, and CHANGED is a PackageChange object".
        list.

        """
        output = subprocess.check_output(["rpm-ostree",
                                         "db",
                                         "diff",
                                         "--format=diff",
                                         "--repo=" + self.repopath,
                                         from_ref,
                                         to_ref])
        added = []
        removed = []
        changed = []
        current_from_package = None
        for line in StringIO(output):
            if line.startswith('ostree diff commit '):
                continue
            line = line.strip()
            change = line[0]
            rpm = line[1:]
            if '!' == change:
                current_from_package = rpm
            elif '=' == change:
                assert current_from_package is not None
                changed.append(PackageChange(current_from_package, rpm))
                current_from_package = None
            elif '-' == change:
                removed.append(rpm)
            elif '+' == change:
                added.append(rpm)
        return (changed, added, removed)

    def prune_history_before(self, ref, date):
        """Delete all commits which are older than the given date,
        which should be an instance of GLib.DateTime().
        """

        [_,rev] = self.repo.resolve_rev(ref, False)
        commit = None
        iter_rev = rev
        n_deleted = 0
        while iter_rev is not None:
            cur_rev = iter_rev
            _,commit = self.repo.load_variant(OSTree.ObjectType.COMMIT, cur_rev)
            iter_rev = OSTree.commit_get_parent(commit)

            ts = OSTree.commit_get_timestamp(commit)
            tsdate = GLib.DateTime.new_from_unix_utc(ts)

            diff_secs = tsdate.difference(date) / GLib.USEC_PER_SEC

            if diff_secs > 0:
                continue
                
            logging.info("Deleting commit {0} {1} seconds in the past".format(cur_rev, diff_secs))
            n_deleted += 1
        logging.info("Deleted {0} commits".format(n_deleted))

    def compose_process(self, treefile, version=None, stdout=None, stderr=None):
        """Currently a thin wrapper for subprocess."""
        treedata = json.load(open(treefile))
        argv = ['rpm-ostree', 'compose', '--repo=' + self.repopath, 'tree']
        if version is not None:
            argv.append('--add-metadata-string=version=' + version)
        argv.append(treefile)
        subprocess.check_call(argv, stdout=stdout, stderr=stderr)
        [_,rev] = self.repo.resolve_rev(treedata['ref'], True)
        return rev

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    r = RpmOstreeComposeRepo(sys.argv[1])
    ref = sys.argv[2]
    r.delete_commits_with_key(ref, 'foo.staging')
    r.prune_history_before(ref, GLib.DateTime.new_now_utc().add_days(-14))
    print "%r" % (r.pkgdiff(ref + '^', ref), )
    r.compose_process(treefile=sys.argv[3],
                      version='42')
