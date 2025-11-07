# Visual APT Manager for Debian
![BadgeVersion](https://img.shields.io/badge/version-1.1-blue)
![BadgeVersion](https://img.shields.io/badge/tag-v1.1-green?link=https%3A%2F%2Fgithub.com%2Fbruneo32%2Fvapt%2Freleases%2Ftag%2Fv1.1)

Visual APT Manager is a simple GUI for APT package management.

### Current features
- Search packages
- Install packages
- Upgrade packages
- Show package details
- Remove packages

### Roadmap
> Missing features? [Open an issue](https://github.com/bruneo32/vapt/issues) suggesting them.
- `v1.2`
  1. Install local deb files
  2. Search by description
  3. Filters
  4. Tooltips
- *Planned*
  - Actions: autoremove, autoclean, etc.
  - apt-mark support
  - Manage multiarch settings

# Installation
Download the latest version from [Releases](https://github.com/bruneo32/vapt/releases/latest), and install it.
```sh
sudo apt install ./vapt_1.1-1_all.deb
```

# Build
There is no building process because it's just python, but you can wrap up the package.
```sh
make package
make release # Rename the package for distribution
```

For one-shot testing:
```sh
make test
```

# License
- Gartoon Redux Action: https://www.iconarchive.com/show/gartoon-action-icons-by-gartoon-team.html
- Gartoon Redux Categories: https://www.iconarchive.com/show/gartoon-categories-icons-by-gartoon-team.html
