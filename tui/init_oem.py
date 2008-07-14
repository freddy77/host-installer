# Copyright (c) 2005-2006 XenSource, Inc. All use and distribution of this 
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by XenSource, Inc. All other rights reserved.
# Xen, XenSource and XenEnterprise are either registered trademarks or 
# trademarks of XenSource Inc. in the United States and/or other countries.

###
# XEN CLEAN INSTALLER
# 'Init' text user interface
#
# written by Andrew Peace

from snack import *
from version import *

import tui
import init_constants
import generalui
import uicontroller
from uicontroller import LEFT_BACKWARDS, RIGHT_FORWARDS, REPEAT_STEP
import tui.network
import repository
import snackutil
import os
import stat
import diskutil
import util

def get_keymap():
    entries = generalui.getKeymaps()

    (button, entry) = ListboxChoiceWindow(
        tui.screen,
        "Select Keymap",
        "Please select the keymap you would like to use:",
        entries,
        ['Ok'], height = 8, scroll = 1)

    return entry

def choose_operation():
    entries = [ 
        (' * Install %s to flash disk' % BRAND_SERVER, init_constants.OPERATION_INSTALL_OEM_TO_FLASH),
        (' * Install %s to hard disk' % BRAND_SERVER, init_constants.OPERATION_INSTALL_OEM_TO_DISK),
        ]

    (button, entry) = ListboxChoiceWindow(tui.screen,
                                          "Welcome to %s" % PRODUCT_BRAND,
                                          """Please select an operation:""",
                                          entries,
                                          ['Ok', 'Exit and reboot'], width=70)

    if button == 'ok' or button == None:
        return entry
    else:
        return -1

# Set of questions to pose if install "to flash disk" is chosen
def recover_pen_drive_sequence():
    answers = {}
    uic = uicontroller
    seq = [
        uic.Step(get_flash_blockdev_to_recover),
        uic.Step(get_image_media),
        uic.Step(get_remote_file, predicates = [lambda a: a['source-media'] != 'local']),
        uic.Step(get_local_file,  predicates = [lambda a: a['source-media'] == 'local']),
        uic.Step(confirm_recover_blockdev),
        ]
    rc = uicontroller.runSequence(seq, answers)

    if rc == -1:
        return None
    else:
        return answers


# Set of questions to pose if install "to hard disk" is chosen
def recover_disk_drive_sequence():
    answers = {}
    uic = uicontroller
    seq = [
        uic.Step(get_disk_blockdev_to_recover),
        uic.Step(get_image_media),
        uic.Step(get_remote_file, predicates = [lambda a: a['source-media'] != 'local']),
        uic.Step(get_local_file,  predicates = [lambda a: a['source-media'] == 'local']),
        uic.Step(confirm_recover_blockdev),
        ]
    rc = uicontroller.runSequence(seq, answers)

    if rc == -1:
        return None
    else:
        return answers

# Offer a list of block devices to the user
def get_blockdev_to_recover(answers, flashonly):

    TYPE_ROM = 5
    def device_type(dev):
        try:
            return int(open("/sys/block/%s/device/type" % dev).read())
        except:
            return None

    # create a list of the disks to offer
    if flashonly:
        disks = [ dev for dev in diskutil.getRemovableDeviceList() if device_type(dev) not in [None, TYPE_ROM] ]
    else:
        disks = diskutil.getDiskList()

    # Create list of (comment,device) tuples for listbox
    entries = [ ("%s %s %d MB" % diskutil.getExtendedDiskInfo(dev,inMb=1), dev) for dev in disks ]

    if entries:
        result, entry = ListboxChoiceWindow(
            tui.screen,
            flashonly and "Select removable device" or "Select drive",
            "Please select on which device you would like to install:",
            entries, ['Ok', 'Back', 'Rescan'])
    else:
        result = ButtonChoiceWindow(
            tui.screen, "No drives found",
            flashonly and "No writable and removable drives were discovered" or "No hard drives found",
            ['Rescan','Back'])
        if result in [None, 'rescan']: return REPEAT_STEP
        if result == 'back':           return LEFT_BACKWARDS

    answers['primary-disk'] = "/dev/" + entry
    if result in [None, 'ok']: return RIGHT_FORWARDS
    if result == 'back':       return LEFT_BACKWARDS
    if result == 'rescan':     return REPEAT_STEP

def get_flash_blockdev_to_recover(answers):
    return get_blockdev_to_recover(answers, flashonly=True)

def get_disk_blockdev_to_recover(answers):
    return get_blockdev_to_recover(answers, flashonly=False)

def get_image_media(answers):
    entries = [
        ('Removable media', 'local'),
        ('HTTP or FTP', 'url'),
        ('NFS', 'nfs')
        ]
    result, entry = ListboxChoiceWindow(
        tui.screen,
        "Image media",
        "Please select where you would like to load image from:",
        entries, ['Ok', 'Back'])

    answers['source-media'] = entry

    if result in ['ok', None]: return RIGHT_FORWARDS
    if result == 'back': return LEFT_BACKWARDS

def get_remote_file(answers):

    # Bring up networking first
    if tui.network.requireNetworking(answers) != 1:
        return LEFT_BACKWARDS

    if answers['source-media'] == 'url':
        text = "Please enter the URL for your HTTP or FTP image"
        label = "URL:"
    elif answers['source-media'] == 'nfs':
        text = "Please enter the server and path of your NFS share (e.g. myserver:/path/to/file)"
        label = "NFS Path:"
        
    if answers.has_key('source-address'):
        default = answers['source-address']
    else:
        default = ""
    (button, result) = EntryWindow(
        tui.screen,
        "Specify image",
        text,
        [(label, default)], entryWidth = 50,
        buttons = ['Ok', 'Back'])
    if button == 'back': return LEFT_BACKWARDS

    dirname   = os.path.dirname(result[0])
    basename  = os.path.basename(result[0])

    if answers['source-media'] == 'nfs':
        accessor  = repository.NFSAccessor(dirname)
    else:
        accessor  = repository.URLAccessor(dirname)

    try:
        accessor.start()
    except:
        ButtonChoiceWindow(
            tui.screen, "Directory inaccessible",
            """Unable to access directory.  Please check the address was valid and try again""",
            ['Back'])
        return LEFT_BACKWARDS

    if not accessor.access(basename):
        ButtonChoiceWindow(
            tui.screen, "Image not found",
            """The image was not found at the location specified.  Please check the file name was valid and try again""",
            ['Back'])
        accessor.finish()
        return LEFT_BACKWARDS
    else:
        answers['image-fd'] = accessor.openAddress(basename)
        answers['image-name'] = basename
        answers['accessor'] = accessor    # This is just a way of stopping GC on this object

    if answers['source-media'] == 'nfs':
        fullpath = os.path.join(accessor.location, basename)
        answers['image-size'] = os.stat(fullpath).st_size
    else:
        answers['image-size'] = 900000000 # A GUESS!

    return RIGHT_FORWARDS
 
def get_local_file(answers):

    # build dalist, a list of accessor objects to mounted CDs and USB partitions
    dev2write = answers["primary-disk"][5:] # strip the 5-char "/dev/" off
    removable_devs = diskutil.getRemovableDeviceList()
    if dev2write in removable_devs: removable_devs.remove(dev2write)
    dalist = []

    removable_devs_and_ptns = []
    for check in removable_devs:
        removable_devs_and_ptns.append(check)
        # if check doesn't end in a numeral, it may have partitions
        # that need to be scanned
        if check[-1] < '0' or check[-1] > '9':
            files = os.listdir('/dev')
            for ptn in filter( lambda x : x[:len(check)] == check, files):
                removable_devs_and_ptns.append(ptn)

    for check in removable_devs_and_ptns:
        device_path = "/dev/%s" % check
        if not os.path.exists(device_path):
            # Device path doesn't exist (maybe udev renamed it).  Create it now.
            major, minor = map(int, open('/sys/block/%s/dev' % check).read().split(':'))
            os.mknod(device_path, 0600|stat.S_IFBLK, os.makedev(major,minor))
        da = repository.DeviceAccessor(device_path)
        try:
            da.start()
        except util.MountFailureException:
            pass
        else:
            dalist.append(da)

    # build list for entry box.  Displayed value is the file name
    entries = []
    for da in dalist:
        mountpoint = da.location
        files = os.listdir(mountpoint)
        entries.extend([ ("%s (%s)" % (f,da.mount_source), (f,da)) for f in files if f.startswith("oem-") and f.endswith(".img.bz2") ])

    if entries:
        # Create list of (comment,device) tuples for listbox
        vendor, model, _ = diskutil.getExtendedDiskInfo(dev2write)
        result, entry = ListboxChoiceWindow(
            tui.screen,
            "Select Image",
            "Please select which image you would like to copy to \"%(vendor)s, %(model)s\":" % locals(),
            entries, ['Ok', 'Back'])
        if result == 'back': return LEFT_BACKWARDS * 2
    else: 
        ButtonChoiceWindow(
            tui.screen, "No images found",
            "No images were found in any CD/DVD drives",
            ['Back'])
        return LEFT_BACKWARDS * 2

    filename = entry[0]
    da       = entry[1]
    fullpath = os.path.join(da.location, filename)

    answers['image-fd'] = open(fullpath, "rb")
    answers['image-name'] = filename
    answers['image-size'] = os.stat(fullpath).st_size
    answers['accessor'] = da    # This is just a way of stopping GC on this object

    return RIGHT_FORWARDS

def confirm_recover_blockdev(answers):
    dev = answers["primary-disk"][5:] # strip the 5-char "/dev/" off
    vendor, model, _ = diskutil.getExtendedDiskInfo(dev)
    rc = snackutil.ButtonChoiceWindowEx(
        tui.screen,
        "Confirm Recover",
        "Are you sure you want to recover the installation on device \"%(vendor)s, %(model)s\"\n\nYour existing installation will be overwritten\n\nTHIS OPERATION CANNOT BE UNDONE." % locals(),
        ['Recover', 'Back'], default=1, width=50
        )

    if rc in ['recover', None]: return RIGHT_FORWARDS

    # Close the file descriptor otherwise it will may not be possible to destroy the accessor
    answers['image-fd'].close()
    return LEFT_BACKWARDS * 3 # back to get image_media
