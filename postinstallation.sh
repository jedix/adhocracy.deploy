#!/bin/sh
### BEGIN INIT INFO
# Provides:          postinstallation
# Required-Start:    $all
# Required-Stop:     $local_fs $remote_fs
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: performs post installation tasks
# Description:       installs adhocracy after debian installation 
### END INIT INFO

case "$1" in
  start)
	aptitude -y install sudo && usermod -g sudo adhocracy
	echo "adhocracy ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers
    su - adhocracy -c "wget -nv https://raw.github.com/liqd/adhocracy.buildout/master/build_debian.sh -O build_debian.sh && sh build_debian.sh @@@BUILD-PARAMETERS@@@"
	cat >> /home/adhocracy/adhocracy_buildout/parts/supervisor/supervisord.conf <<EOF
[program:adhocracy]
command = /home/adhocracy/adhocracy_buildout/bin/paster serve /home/adhocracy/adhocracy_buildout/etc/adhocracy.ini
process_name = adhocracy
directory = /home/adhocracy/adhocracy_buildout/bin
priority = 45
redirect_stderr = false
EOF

	update-rc.d -f postinstallation remove
	halt
  ;;
esac

