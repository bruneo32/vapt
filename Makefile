
all: package check

.PHONY: clean package check release

clean:
	rm -rf dist vapt.deb

package:
	dpkg-deb -Zgzip --build vapt vapt.deb

check:
	dpkg-deb -I vapt.deb
	dpkg-deb -c vapt.deb

release: package
	mkdir -p dist
	mv vapt.deb dist/vapt.deb
	dpkg-name -o dist/vapt.deb
