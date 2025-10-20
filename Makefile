
all: package

.PHONY: clean package check

clean:
	rm -rf dist vapt.deb

package:
	mkdir -p dist
	dpkg-deb -Zgzip --build vapt vapt.deb
	cp vapt.deb dist/vapt.deb
	dpkg-name -o dist/vapt.deb

check:
	dpkg-deb -I vapt.deb
	dpkg-deb -c vapt.deb
