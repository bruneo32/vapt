
all: test

.PHONY: clean test package check release

clean:
	rm -rf dist vapt.deb

test:
	sudo VAPT_CONFIG_PATH=${HOME}/.config/vapt.yml vapt/usr/bin/vapt.py

package:
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
