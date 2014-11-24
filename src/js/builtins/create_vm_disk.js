// -*- indent-tabs-mode: nil; tab-width: 2; -*-
// Copyright (C) 2013 Colin Walters <walters@verbum.org>
//
// This library is free software; you can redistribute it and/or
// modify it under the terms of the GNU Lesser General Public
// License as published by the Free Software Foundation; either
// version 2 of the License, or (at your option) any later version.
//
// This library is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
// Lesser General Public License for more details.
//
// You should have received a copy of the GNU Lesser General Public
// License along with this library; if not, write to the
// Free Software Foundation, Inc., 59 Temple Place - Suite 330,
// Boston, MA 02111-1307, USA.

const GLib = imports.gi.GLib;
const Gio = imports.gi.Gio;
const Lang = imports.lang;

const GSystem = imports.gi.GSystem;
const OSTree = imports.gi.OSTree;

const Toolbox = imports.gi.Toolbox;

const Builtin = imports.builtin;
const ArgParse = imports.argparse;
const ProcUtil = imports.procutil;
const LibQA = imports.libqa;
const GuestFish = imports.guestfish;

const CreateVmDisk = new Lang.Class({
    Name: 'CreateVmDisk',
    Extends: Builtin.Builtin,

    DESCRIPTION: "Generate a qcow2 disk image",

    _init: function() {
        this.parent();
        this.parser.addArgument('--unconfigured-state', { description: 'Error mesage to use if OS needs further configuration' });
        this.parser.addArgument('--origin-url', { description: 'URL for origin remote' });
        this.parser.addArgument('repo');
        this.parser.addArgument('osname');
        this.parser.addArgument('ref');
        this.parser.addArgument('diskpath');
    },

    execute: function(args, loop, cancellable) {

        let enforcing = ProcUtil.runSyncGetOutputUTF8Stripped(['getenforce'], cancellable);
        if (enforcing != 'Disabled') {
            throw new Error("SELinux must be disabled; see https://bugzilla.redhat.com/show_bug.cgi?id=1060423");
        }

        Toolbox.unshare_namespaces(Toolbox.NamespaceFlags.MOUNT);
        Toolbox.remount_rootfs_private();

        let repoPath = Gio.File.new_for_path(args.repo);
        let repo = new OSTree.Repo({ path: repoPath });
        let [,rev] = repo.resolve_rev(args.ref, false);
        let path = Gio.File.new_for_path(args.diskpath);
        if (path.query_exists(null))
            throw new Error("" + path.get_path() + " exists");
        let tmppath = path.get_parent().get_child(path.get_basename() + '.tmp');
        GSystem.shutil_rm_rf(tmppath, cancellable);
        LibQA.createDisk(tmppath, cancellable);
        let tmpdir = Gio.File.new_for_path(GLib.dir_make_tmp('rpmostreetoolbox.XXXXXX'));
        let mntdir = tmpdir.get_child('mnt');
        GSystem.file_ensure_directory(mntdir, true, cancellable);
        let gfmnt = new GuestFish.GuestMount(tmppath, { partitionOpts: LibQA.DEFAULT_GF_PARTITION_OPTS,
                                                            readWrite: true });
        gfmnt.mount(mntdir, cancellable);
        try {
            let osname = args['osname'];
            LibQA.pullDeploy(mntdir, repoPath, osname, args.ref, rev, args.origin_url,
                             cancellable, { addKernelArgs: [], unconfiguredState: args.unconfigured_state });
            print("Doing initial labeling");
            ProcUtil.runSync(['ostree', 'admin', '--sysroot=' + mntdir.get_path(),
                              'instutil', 'selinux-ensure-labeled',
		                          mntdir.get_path(),
		                          ""],
		                         cancellable,
		                         { logInitiation: true });
            let [sysroot, current] = LibQA.getSysrootAndCurrentDeployment(mntdir, osname);
            let deployDir = sysroot.get_deployment_directory(current);
            let etcSysconfigDockerStorage = deployDir.resolve_relative_path('etc/sysconfig/docker-storage');
            if (etcSysconfigDockerStorage.query_exists(null)) {
                print("Updating Docker storage: " + etcSysconfigDockerStorage.get_path());
                etcSysconfigDockerStorage.replace_contents('DOCKER_STORAGE_OPTIONS=--storage-opt dm.fs=xfs --storage-opt dm.datadev=/dev/mapper/atomicos-docker--data --storage-opt dm.metadatadev=/dev/mapper/atomicos-docker--meta\n', null, false, 0, null);
            } else {
                print("No Docker storage config detected in " + etcSysconfigDockerStorage.get_path());
            }
        } finally {
            gfmnt.umount(cancellable);
        }
        GSystem.file_rename(tmppath, path, cancellable);
        GSystem.shutil_rm_rf(tmpdir, cancellable);
        print("Created: " + path.get_path());
    }
});
