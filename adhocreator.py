import BaseHTTPServer
import ConfigParser
import getopt
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib
import urlparse
import xml.dom.minidom as dom
from threading import Thread
from time import sleep

class SystemCheck(object):
    def __init__(self):
        """Perform basic system check."""
        self.passed = True
        if not self.check_vboxmanage() or not self.check_vboxconfig():
            self.passed = False

    def check_vboxmanage(self):
        try:
            proc = subprocess.check_output("VBoxManage")
        except OSError as e:
            print "Could not execute 'VBoxManage'. It seems virtualbox is not installed on your system."
            print "Try: sudo apt-get install virtualbox"
            return False
        return True

    def check_vboxconfig(self):
        configfile = os.getenv("HOME") + "/.VirtualBox/VirtualBox.xml"
        try:
            self.machine_folder = dom.parse(configfile).getElementsByTagName("SystemProperties")[0].getAttribute("defaultMachineFolder")
        except IOError as e:
            print "VirtualBox config file not found. Does the following file exist?"
            print configfile
            return False
        return True
        
    def  check_configfile(self, configfile):
        return True

class Config(object):
    def __init__(self, configfile, section="SETTINGS"):
        self.config = ConfigParser.ConfigParser()
        self.config.read(configfile)
        self.section = section

    def set_section(self, section):
        self.section = section

    def get(self, option, default=None):
        if self.config.has_option(self.section, option):
            return self.config.get(self.section, option)
        else:
            return default

class VMManager(object):
    def __init__(self, machine_folder):
        self.vms = self.get_vms()
        self.machine_folder = machine_folder

    def get_vms(self, get_running=False):
        vmtype = "vms"
        if get_running:
            vmtype = "running%s"%vmtype
        vmsoutput = subprocess.check_output(["VBoxManage", "list", vmtype])
        vmslist = vmsoutput.split("\n")[:-1]
        vms = []
        for vm in vmslist:
            res = re.search(r'"(.*)" {(.*)}', vm)
            vms.append([res.group(1), res.group(2)])
        return vms

    def show_vms(self):
        i = 0
        running_vms = self.get_vms(True)
        for vm in self.vms:
            i += 1
            if vm in running_vms:
                running = " (running)"
            else:
                running = ""
            print "%2d: %s (%s)%s" % (i, vm[0], vm[1], running)

class VM(object):
    def __init__(self, manager, configfile):
        self.manager = manager
        self.vmconfig = Config(configfile)
        self.tempdir = tempfile.mkdtemp()
        self.name = self.get_unique_name()
        self.create_vm(self.name)
        self.edit_vm()
        self.create_harddisk(".".join([self.name, ".vdi"]), self.vmconfig.get("disk-size", "8000"))
        self.prepare_preseed()
        self.start_vm()

    def vboxmanage(self, options, get_output=False, show_output=False):
        options.insert(0, "VBoxManage")
        try:
            if get_output:
                output = subprocess.check_output(options, stderr=subprocess.STDOUT)
            else:
                if show_output:
                    subprocess.check_call(options)
                else:
                    subprocess.check_call(options, stdout=open(os.devnull, "w"), stderr=open(os.devnull, "w"))
                output = True
        except subprocess.CalledProcessError as e:
            return False
        return output

    def get_unique_name(self):
        name = "-".join([str(os.getpid()),str(int(time.time()))])
        if name in (vm[0] for vm in self.manager.get_vms()):
            print "Could not get a unique name. Please try again."
            exit(1)
        return name

    def create_vm(self, name):
        if not self.vboxmanage(["createvm", "--name", name, "--register", "--ostype", "Debian"]):
            print "Could not create virtual machine."
            exit(1)

    def edit_vm(self):
        self.modify_attribute("--cpus", self.vmconfig.get("cpus", "1"))
        self.modify_attribute("--memory", self.vmconfig.get("memory", "1024"))
        self.modify_attribute("--nic1", "nat")
        self.modify_attribute("--nictype1", "Am79C973")
        self.modify_attribute("--vrde", "on")
        self.modify_attribute("--boot4", "net")
        self.vboxmanage(["controlvm", self.name, "natpf1", "adhocracy-webserver,tcp,,5001,,5001"])
        self.vboxmanage(["controlvm", self.name, "natpf1", "ssh,tcp,,2222,,22"])

    def create_harddisk(self, filename, size):
        filename = '/'.join([self.get_vm_folder(), filename])
        if not self.vboxmanage(["createhd", "--filename", filename, "--size", size, "--format", "VDI"]):
            print "Could not create virtual hdd '%s'." % filename
            exit(1)
        if not self.vboxmanage(["storagectl", self.name, "--name", "SATA Controller", "--add", "sata", "--controller", "IntelAhci", "--sataportcount", "2"]):
            print "Could not create storage controller."
            exit(1) 
        if not self.vboxmanage(["storageattach", self.name, "--storagectl", "SATA Controller", "--type", "hdd", "--port", "0", "--device", "0", "--medium", filename]):
            print "Could not attach storage to virtual machine."
            exit(1)

    def dlProgress(self, count, blockSize, totalSize):
        if totalSize < count * blockSize:
            totalSize = count * blockSize if count * blockSize  > 0 else 1  
        percent = int(count*blockSize*100/totalSize)
        sys.stdout.write("\r[")
        done = int(percent * 70 / 100)
        for i in range(0,70):
            char = "#" if i < done else " "
            sys.stdout.write(char)
        sys.stdout.write("] %d%%" % percent)
        sys.stdout.flush()
      
    def get_vm_folder(self):
        vminfo = self.vboxmanage(["showvminfo", self.name, "--machinereadable"], get_output=True)
        if vminfo == False:
            print "Virtual machine with name '%s' not found."%name
            exit(1)
        root = "ROOT"
        vminfo = "[%s]\n%s" % (root, vminfo)
        config = ConfigParser.ConfigParser()
        config.readfp(io.BytesIO(vminfo))
        return os.path.dirname(config.get(root, "CfgFile")[1:-1])

    def modify_attribute(self, attribute, value):
        if not self.vboxmanage(["modifyvm", self.name, attribute, value]):
            print "Could not set %s to %s for machine '%s'." % (attribute, value, self.name)
            pass

    def stop_vm(self):
        self.vboxmanage(["controlvm", self.name, "poweroff"])
        sleep(4)

    def prepare_preseed(self):
        dist = self.vmconfig.get("dist", "squeeze")
        bootimage = "http://ftp.debian.org/debian/dists/%s/main/installer-amd64/current/images/netboot/netboot.tar.gz" % dist
        preseed_url = self.vmconfig.get("preseed-url", "https://raw.github.com/jedix/adhocracy.deploy/master/adhocracy.preseed")
        post_install_url = self.vmconfig.get("post-install-url", "https://raw.github.com/jedix/adhocracy.deploy/master/postinstallation.sh")
        preseed_filename = "%s.preseed" % self.name
        post_install_filename = "%s-postinstall" % self.name
        self.download(preseed_url, "%s/%s" % (self.tempdir, preseed_filename))
        self.download(post_install_url, "%s/%s" % (self.tempdir, post_install_filename))
        self.fileserver =  FileServer(self.tempdir, [preseed_filename, post_install_filename])
        
        hostname = self.vmconfig.get("hostname", "adhocracyvm")
        preseed_url = "http://10.0.2.2:%s/%s" % (str(self.fileserver.port), preseed_filename)
        post_install_url = "http://10.0.2.2:%s/%s" % (str(self.fileserver.port), post_install_filename)
        
        preseed_file = open(self.tempdir + "/" + preseed_filename, "r")
        preseed_file_content = preseed_file.read().replace("@@@POST-INSTALL-URL@@@", post_install_url)
        preseed_file.close()
        preseed_file = open(self.tempdir + "/" + preseed_filename, "w")
        preseed_file.write(preseed_file_content)
        preseed_file.close()
        
        self.download(bootimage, "%s/netboot.tar.gz" % self.tempdir)
        tftp_path = os.getenv("HOME") + "/.VirtualBox/TFTP"
        if not os.path.exists(tftp_path):
            os.mkdir(tftp_path)
        tar = tarfile.open(self.tempdir + "/netboot.tar.gz", "r:gz")
        tar.extractall(tftp_path)
        os.rename("%s/pxelinux.0" % tftp_path, "%s/%s.pxe" % (tftp_path, self.name))
        txt = "default install\nlabel install\n\tmenu label ^Install\n\tmenu default\n\tkernel debian-installer/amd64/linux\n\t"
        txt = "%sappend vga=788 auto-install/enable=true initrd=debian-installer/amd64/initrd.gz hostname=%s domain= preseed/url=%s" % (txt, hostname, preseed_url)
        txt_file = open(tftp_path + "/debian-installer/amd64/boot-screens/txt.cfg", "w")
        txt_file.write(txt)
        txt_file.close()
        syslinux = "include debian-installer/amd64/boot-screens/menu.cfg\ndefault debian-installer/amd64/boot-screens/vesamenu.c32\nprompt 0\ntimeout 1"
        syslinux_file = open(tftp_path + "/debian-installer/amd64/boot-screens/syslinux.cfg", "w")
        syslinux_file.write(syslinux)
        syslinux_file.close()
        

    def start_vm(self):
        if not self.vboxmanage(["startvm", self.name]):
            print "Could not start virtual machine."
            exit(1)

    def download(self, url, filename):
        try:
            urllib.urlretrieve(url, filename, reporthook=self.dlProgress)
            sys.stdout.write("\n")
        except IOError as e:
            print "Could not download %s" % url
            exit(1)

class LittleHTTPServer(BaseHTTPServer.HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, directory, files):
        BaseHTTPServer.HTTPServer.__init__(self, server_address, RequestHandlerClass)
        self.files = files
        self.served_file = ""
        self.directory = directory

class LittleHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path[1:] in self.server.files: 
            self.server.served_file = self.path[1:]
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.send_header("Content-Disposition", "attachment; filename=\"%s\"" % self.path[1:])
            self.end_headers()
            f = open(self.server.directory + "/" + self.path[1:], 'r')
            self.wfile.write(f.read())
            f.close()
        return

    def log_message(self, format, *args):
        return

class FileServer(Thread):
    def __init__(self, directory="", files=[], port=0):
        server_class = LittleHTTPServer
        server_address = ('0.0.0.0', port)
        handler_class = LittleHandler
        self.server = server_class(server_address, handler_class, directory, files)
        self.server.timeout = 1
        self.port = self.server.server_address[1]
        self.keep_running = True
        Thread.__init__(self)
        self.start()
    
    def run(self):
        while self.keep_running:
            self.server.handle_request()

    def close(self):
        self.server.socket.close()
        self.keep_running = False

def usage():
    usage = """
    -h --help                 Prints this help
    -f --config (configfile)  Configuration file
    -c --check                Check configuration
    """
    print usage

def main(argv):
    try:
        opt, args = getopt.getopt(argv, "hf:cl", ["help", "config=", "check", "listvms"])
    except getopt.GetoptError, err:
        print str(err)
        usage()
        sys.exit(2)

    list_vms = False
    check_config = False
    uid = None
    create_vm = False
    configfile = "default.cfg"

    for option, value in opt:
        if option in ("-h", "--help"):
            usage()
            sys.exit()
        elif option in ("-f", "--config"):
            configfile = value
        elif option in ("-c", "--check"):
            check_config = True
        elif option in ("-l", "--list"):
            list_vms = True
        else:
            assert False, "unhandled option"
            
    check = SystemCheck()
    if not check.passed:
        exit(1)
    if not check.check_configfile(configfile):
        exit(1)
    if check_config:
        exit(0)

    manager = VMManager(check.machine_folder)
    if list_vms:
        manager.show_vms()

    vm = VM(manager, configfile)
    try:
        my_in = raw_input("Press ENTER as soon as the new virtual machine is shut down.")
    except KeyboardInterrupt as e:
        pass
    vm.fileserver.close()
    shutil.rmtree(vm.tempdir)
    vm.vboxmanage(["export", vm.name, "-o", "%s.ova"%vm.name], show_output=True)
    print "Finished."
    exit(0)
    
if __name__ == "__main__":
    main(sys.argv[1:])
