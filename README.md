# Visual APT Manager
Visual APT Manager is a simple GUI for APT package management
for Debian based distros *(Debian, Ubuntu, Linux Mint, Pop_OS!, etc)*.

[![Release](https://img.shields.io/github/v/release/bruneo32/vapt)](https://github.com/bruneo32/vapt/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/bruneo32/vapt/total?style=social)](https://github.com/bruneo32/vapt/releases)
![Stars](https://img.shields.io/github/stars/bruneo32/vapt?style=social)\
[![Python](https://img.shields.io/badge/Python-3.7+-blue)](https://www.python.org/downloads/release/python-370/)
[![Debian](https://img.shields.io/badge/Debian-11+-brightgreen)](https://www.debian.org/releases/bullseye/index.en.html)
[![Ubuntu](https://img.shields.io/badge/Ubuntu-20.04+-orange)](https://www.releases.ubuntu.com/focal/)\
[![License](https://img.shields.io/github/license/bruneo32/vapt)](LICENSE)
[![Commits](https://img.shields.io/github/commit-activity/m/bruneo32/vapt)](https://github.com/bruneo32/vapt/commits/main)


### Current features
- Install **local *deb*** files
- **Search** packages
- **Install** packages
- **Upgrade** packages
- **Remove** packages
- Show package **details**

### Roadmap
> Missing features? [Open an issue](https://github.com/bruneo32/vapt/issues) suggesting them.
- *Planned*
  - Refactor into python modules
  - Actions: autoremove, autoclean, etc.
  - apt-mark support
  - Manage multiarch settings

# Installation
Download the latest version from [Releases](https://github.com/bruneo32/vapt/releases), and install it.
```sh
sudo apt install ./vapt_1.2-4_all.deb
```

# Build
There is no building process because it's just *python*, but you can wrap up the package.
```sh
make package
make release # Rename the package for distribution
```

For one-shot testing:
```sh
make test
```

# Licenses
- Logo derived from: https://www.debian.org/logos/
- Gartoon Redux Action: https://www.iconarchive.com/show/gartoon-action-icons-by-gartoon-team.html
- Gartoon Redux Categories: https://www.iconarchive.com/show/gartoon-categories-icons-by-gartoon-team.html
- Filter icon: https://www.iconarchive.com/show/mono-general-4-icons-by-custom-icon-design/filter-icon.html
- Loading GIF: https://loading.io
