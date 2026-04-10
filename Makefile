
all: test

.PHONY: clean test package check release

clean:
	@echo "+ Cleaning git-ignored files..."
	git clean -Xdf

test:
	sudo XAUTHORITY=${XAUTHORITY} VAPT_CONFIG_PATH=${HOME}/.config/vapt.yml vapt/usr/bin/vapt.py

package:
	@echo "+ Copy LICENSE"
	@mkdir -p vapt/usr/share/doc/vapt
	@cp LICENSE vapt/usr/share/doc/vapt/copyright

	@echo "+ Processing deb_control..."
	@cp deb_control vapt/DEBIAN/control

	@SIZE=$$(du -sk vapt --exclude=vapt/DEBIAN | cut -f1); \
	sed -i "/^Architecture:/a Installed-Size: $$SIZE" vapt/DEBIAN/control;

	@echo "+ Generating md5sums..."
	@cd vapt && find . -type f -not -path "./DEBIAN/*" -exec md5sum {} \; > DEBIAN/md5sums && cd ..

	@echo "+ Building package..."
	dpkg-deb -Zgzip --build vapt vapt.deb

check:
	dpkg-deb -I vapt.deb
	dpkg-deb -c vapt.deb

release: package
	mkdir -p dist
	mv vapt.deb dist/vapt.deb
	dpkg-name -o dist/vapt.deb

install:
	sudo apt install --reinstall ./vapt.deb
