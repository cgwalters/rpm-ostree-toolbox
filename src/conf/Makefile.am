EXTRA_DIST = rpm-ostree-toolbox.conf

# Heads-up: the installed file does not have the .conf extension
install-conf: $(EXTRA_DIST)
	$(MKDIR_P)                    $(DESTDIR)$(sysconfdir)/sysconfig
	$(INSTALL_DATA) $(EXTRA_DIST) $(DESTDIR)$(sysconfdir)/sysconfig/rpm-ostree-toolbox

install-data-local: install-conf
