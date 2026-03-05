#!/usr/bin/env python3
import re
import sys
import glob
import os.path
import yaml
import atexit
import threading
import subprocess
from PIL import Image

# fmt: off
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk, Gdk, Gio, GdkPixbuf, Pango
# fmt: on

# == Configuration == #
user_config_path = os.path.expandvars("$VAPT_CONFIG_PATH") or \
	os.path.expandvars("$HOME/.config/vapt.yml")
os.makedirs(os.path.dirname(user_config_path), exist_ok=True)

user_config = {
	'editor': {
		'l10n_file': '',
		'installs_autocompletion': True,
		'upgrades_selected_by_default': True,
	},
	'apt_install': {
		'fix_missing': True,
		'fix_broken': True,
		'fix_policy': False
	}
}

# == Localization == #
lang_file_path = None
master_lang_file_path = "/usr/share/vapt/l10n/en.yml"

langs_available = [{"display": "", "file": ""}]
l10n_strings = {}
l10n_strings_master = {}


def Localize(key: str) -> str:
	global l10n_strings
	global l10n_strings_master
	if key in l10n_strings:
		return l10n_strings[key]
	if key in l10n_strings_master:
		return l10n_strings_master[key]
	return key


# == APT Util == #
APT_LANG = ["env", "LANG=C"]
APT_NONINTERACTIVE = ["env", "DEBIAN_FRONTEND=noninteractive"]

# == GTK Util == #


def gtk_image_icon(path: str, size: int) -> Gtk.Image:
	return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(
		filename=path,
		width=size, height=size,
		preserve_aspect_ratio=True
	))

def gtk_gif_icon(path: str, size: int, rate: float) -> Gtk.Image:
	# Open the animated GIF with Pillow
	img_pil = Image.open(path)

	# Create the GTK animation container
	simpleanim = GdkPixbuf.PixbufSimpleAnim.new(size, size, rate)
	simpleanim.set_loop(True)

	# Iterate through all frames
	try:
		while True:
			# Scale the frame and ensure it has an alpha channel
			frame_rgba = img_pil.convert("RGBA")
			frame_scaled = frame_rgba.resize((size, size), Image.Resampling.BILINEAR)

			# Convert Pillow Image data to GLib Bytes
			data = frame_scaled.tobytes()
			glib_bytes = GLib.Bytes.new(data)

			# Create a new Pixbuf from the bytes
			width, height = frame_scaled.size
			rowstride = width * 4  # 4 channels for RGBA

			pbuf = GdkPixbuf.Pixbuf.new_from_bytes(
				glib_bytes,
				GdkPixbuf.Colorspace.RGB,
				True,  # has_alpha
				8,     # bps
				width,
				height,
				rowstride
			)

			# Add animation
			simpleanim.add_frame(pbuf)

			# Move to the next frame in the GIF
			img_pil.seek(img_pil.tell() + 1)

	except EOFError:
		# Pillow throws an EOFError when there are no more frames
		pass

	# Apply to a Gtk.Image and return
	img = Gtk.Image()
	img.set_from_animation(simpleanim)
	return img

def apt_canonicalize_package(name: str, version: str, arch: str) -> str:
	res = name.strip()
	if arch:
		res += ":" + arch.strip()
	if version:
		res += "=" + version.strip()
	return res

def format_filesize(size_bytes: int) -> str:
	"""Convert a filesize in bytes to a human-readable string with binary units."""
	if size_bytes < 0: return "--"

	# Define binary units
	units = ["B", "KB", "MB", "GB", "TB", "PB"]
	size = float(size_bytes)

	for unit in units:
		if size < 1024 or unit == units[-1]:
			# Format to 2 decimal places for sizes >= KiB
			if unit == "B":
				return "%d %s" % (size, unit)
			else:
				return "%.2f %s" % (size, unit)
		size /= 1024

def mkdtemp():
	return subprocess.Popen(
		["mktemp", "-d"],
		stdout=subprocess.PIPE,
		stderr=subprocess.DEVNULL,
		text=True
	).communicate()[0].strip()

def rmforce(dir):
	subprocess.Popen(
		["rm", "-Rf", dir],
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL,
		text=True
	)

# == GTK windows == #

class MainWindow(Gtk.Window):
	def __init__(self):
		global user_config

		super().__init__(title="Visual APT Manager")
		self.set_default_size(640, 480)
		self.set_position(Gtk.WindowPosition.CENTER)

		# Main vertical box to hold toolbar (optional) + notebook
		main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
		self.add(main_box)

		# Create a Notebook (tabs)
		notebook = Gtk.Notebook()
		main_box.pack_start(notebook, True, True, 0)

		btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
		btn_box.set_border_width(6)

		# Get os pretty name
		proc = subprocess.Popen(
			["bash", "-c",
			 "echo \"$(grep '^PRETTY_NAME=' /etc/os-release | cut -d= -f2 | tr -d '\"')\""],
			stdout=subprocess.PIPE,
			stderr=subprocess.DEVNULL,
			text=True
		)
		os_name, _ = proc.communicate()
		os_name = os_name.strip() or "Unknown OS"

		proc = subprocess.Popen(
			["dpkg-deb", "--print-architecture"],
			stdout=subprocess.PIPE,
			stderr=subprocess.DEVNULL,
			text=True
		)
		dpkg_arch, _ = proc.communicate()
		dpkg_arch = dpkg_arch.strip() or "N/A"

		label = Gtk.Label(label=os_name)
		btn_box.pack_start(label, False, False, 0)

		label = Gtk.Label(label="  " + dpkg_arch)
		# label.modify_font(Pango.FontDescription("Bold"))
		btn_box.pack_start(label, False, False, 0)

		# expanding spacer pushes following children to the right
		spacer = Gtk.Box()
		spacer.set_hexpand(True)
		btn_box.pack_start(spacer, True, True, 0)

		button = Gtk.Button()
		button.connect("clicked", lambda _: show_about_dialog())
		image = gtk_image_icon("/usr/share/vapt/images/system-help-icon.png",
							   24)
		button.add(image)
		btn_box.pack_start(button, False, False, 0)

		button = Gtk.Button(label=Localize("str_quit"))
		button.set_halign(Gtk.Align.END)
		button.connect("clicked", lambda button: self.destroy())
		btn_box.pack_start(button, False, False, 0)

		button = Gtk.Button(label=Localize("str_continue"))
		button.set_halign(Gtk.Align.END)
		button.connect("clicked", self.do_everything)
		btn_box.pack_start(button, False, False, 0)

		main_box.pack_start(btn_box, False, False, 0)

		# -----------------------
		# Tab 1: Install package
		# -----------------------
		paned = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

		# Top: Form
		self.apt_list_install_autocomplete = Gtk.ListStore(str)
		entry = Gtk.Entry()
		entry.set_placeholder_text(Localize("str_search_package_by_name"))
		completion = Gtk.EntryCompletion.new()
		completion.set_model(self.apt_list_install_autocomplete)
		completion.set_text_column(0)
		completion.set_inline_completion(True)
		entry.set_completion(completion)

		def _completion_match(completion, key, iter_, user_data):
			if not key:
				return False
			key = key.lower().strip()

			terms = key.split()
			if not terms:
				return False

			model = completion.get_model()
			candidate = model[iter_][0].lower()

			# require first term as prefix
			prefix = terms[0]
			if not candidate.startswith(prefix):
				return False

			# require remaining terms anywhere
			for t in terms[1:]:
				if t not in candidate:
					return False

			return True

		# Set custom matcher
		completion.set_match_func(_completion_match, None)

		# Add debounce time
		self._install_entry_timeout_id = None
		self._debounce_delay_ms = 300

		def _apt_lookup(text):
			terms = text.strip().split(" ")
			prefix = terms[0]
			grep_terms = terms[1:]

			self.apt_list_install_autocomplete.clear()
			if len(text) >= 1:
				for cand in self.lookup_apt_packages(prefix, grep_terms):
					cand = cand.lower().strip()
					self.apt_list_install_autocomplete.append([cand])
			# Force completion popup refresh
			completion.complete()
			return False

		# Whenever the user types, refill store dynamically
		def on_install_entry_changed(editable):
			global user_config

			if not user_config["editor"]["installs_autocompletion"]:
				return

			# Cancel previous scheduled call if it exists
			if getattr(self, "_install_debounce_source", None):
				GLib.source_remove(self._install_entry_timeout_id)
				self._install_entry_timeout_id = None

			text = editable.get_text().lower().strip()
			if not text:
				self.apt_list_install_autocomplete.clear()
				completion.complete()
				return

			# Call with debounce timeout
			self._install_entry_timeout_id = GLib.timeout_add(
				self._debounce_delay_ms,
				_apt_lookup,
				text
			)

		entry.connect("changed", on_install_entry_changed)
		entry.connect("activate", self.on_install_entry_activate)
		paned.pack_start(entry, False, False, 0)

		# Bottom: List
		self.list_install = Gtk.ListStore(bool, str, str, str)
		treeview = Gtk.TreeView(model=self.list_install)
		treeview.set_search_column(1)

		render_toggle = Gtk.CellRendererToggle()
		render_toggle.connect("toggled", self.on_toggle_install)
		column = Gtk.TreeViewColumn(Localize("str_install"),
									render_toggle, active=0)
		column.set_sort_column_id(0)
		treeview.append_column(column)

		column = Gtk.TreeViewColumn(Localize("str_pkg_name"),
									Gtk.CellRendererText(), text=1)
		column.set_sort_column_id(1)
		treeview.append_column(column)
		column = Gtk.TreeViewColumn(Localize("str_pkg_candidate_version"),
									Gtk.CellRendererText(), text=2)
		column.set_sort_column_id(2)
		treeview.append_column(column)
		column = Gtk.TreeViewColumn(Localize("str_pkg_architecture"),
									Gtk.CellRendererText(), text=3)
		column.set_sort_column_id(3)
		treeview.append_column(column)

		treeview.connect("button-press-event", self.on_context_install)

		install_scroll = Gtk.ScrolledWindow()
		install_scroll.set_policy(Gtk.PolicyType.AUTOMATIC,
								  Gtk.PolicyType.AUTOMATIC)
		install_scroll.add(treeview)
		paned.pack_start(install_scroll, True, True, 0)

		# Put paned into notebook tab
		tab1_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		tab1_box.pack_start(paned, True, True, 0)
		notebook.append_page(tab1_box, Gtk.Label(
			label=Localize("str_install")))

		# -----------------------
		# Tab 2: Upgrade
		# -----------------------
		self.list_upgrade = Gtk.ListStore(bool, str, str, str, str)
		self.get_apt_upgradables()

		treeview = Gtk.TreeView(model=self.list_upgrade)
		treeview.set_search_column(1)

		render_toggle = Gtk.CellRendererToggle()
		render_toggle.connect("toggled", self.on_toggle_upgrade)
		column = Gtk.TreeViewColumn(Localize("str_install"),
									render_toggle, active=0)
		column.set_sort_column_id(0)
		treeview.append_column(column)

		column = Gtk.TreeViewColumn(Localize("str_pkg_name"),
									Gtk.CellRendererText(), text=1)
		column.set_sort_column_id(1)
		treeview.append_column(column)
		column = Gtk.TreeViewColumn(Localize("str_pkg_candidate_version"),
									Gtk.CellRendererText(), text=2)
		column.set_sort_column_id(2)
		treeview.append_column(column)
		column = Gtk.TreeViewColumn(Localize("str_pkg_installed_version"),
									Gtk.CellRendererText(), text=3)
		column.set_sort_column_id(3)
		treeview.append_column(column)
		column = Gtk.TreeViewColumn(Localize("str_pkg_architecture"),
									Gtk.CellRendererText(), text=4)
		column.set_sort_column_id(4)
		treeview.append_column(column)

		treeview.connect("button-press-event", self.on_context_upgrade)

		upgrade_scroll = Gtk.ScrolledWindow()
		upgrade_scroll.set_policy(Gtk.PolicyType.AUTOMATIC,
								  Gtk.PolicyType.AUTOMATIC)
		upgrade_scroll.add(treeview)

		notebook.append_page(upgrade_scroll, Gtk.Label(
			label=Localize("str_upgrade")))

		# -----------------------
		# Tab 3: Remove
		# -----------------------
		self.list_remove = Gtk.ListStore(bool, str, str, str)
		self.get_apt_installed()

		treeview = Gtk.TreeView(model=self.list_remove)
		treeview.set_search_column(1)

		render_toggle = Gtk.CellRendererToggle()
		render_toggle.connect("toggled", self.on_toggle_remove)
		column = Gtk.TreeViewColumn(Localize("str_remove"),
									render_toggle, active=0)
		column.set_sort_column_id(0)
		treeview.append_column(column)

		column = Gtk.TreeViewColumn(Localize("str_pkg_name"),
									Gtk.CellRendererText(), text=1)
		column.set_sort_column_id(1)
		treeview.append_column(column)
		column = Gtk.TreeViewColumn(Localize("str_pkg_installed_version"),
									Gtk.CellRendererText(), text=2)
		column.set_sort_column_id(2)
		treeview.append_column(column)
		column = Gtk.TreeViewColumn(Localize("str_pkg_architecture"),
									Gtk.CellRendererText(), text=3)
		column.set_sort_column_id(3)
		treeview.append_column(column)

		treeview.connect("button-press-event", self.on_context_upgrade)

		upgrade_scroll = Gtk.ScrolledWindow()
		upgrade_scroll.set_policy(Gtk.PolicyType.AUTOMATIC,
								  Gtk.PolicyType.AUTOMATIC)
		upgrade_scroll.add(treeview)

		notebook.append_page(upgrade_scroll, Gtk.Label(
			label=Localize("str_remove")))

		# -----------------------
		# Tab 4: Settings
		# -----------------------
		settings_box = Gtk.VBox()
		settings_box.set_border_width(16)
		settings_box.set_spacing(6)

		label = Gtk.Label(label=Localize("str_settings_editor_options"))
		label.set_xalign(0)
		settings_box.pack_start(label, False, False, 0)

		# Label for the combobox
		lang_label = Gtk.Label(
			label="  " + Localize("str_settings_label_language"))
		lang_label.set_xalign(0)

		# Lang combobox
		lang_liststore = Gtk.ListStore(str, str)
		for l in langs_available:
			lang_liststore.append([l["display"], l["file"]])
		langs_combo = Gtk.ComboBox.new_with_model(lang_liststore)
		render_text = Gtk.CellRendererText()
		langs_combo.pack_start(render_text, True)
		langs_combo.add_attribute(render_text, "text", 0)

		active_lang_idx = 0
		if user_config["editor"]["l10n_file"] != "":
			for i, l in enumerate(langs_available):
				if l["file"] == user_config["editor"]["l10n_file"]:
					active_lang_idx = i
		langs_combo.set_active(active_lang_idx)
		langs_combo.connect("changed", self.on_lang_changed)

		# Horizontal box for lang pair
		lang_box = Gtk.HBox(spacing=6)
		lang_box.pack_start(lang_label, False, False, 0)
		lang_box.pack_start(langs_combo, False, False, 0)
		settings_box.pack_start(lang_box, False, False, 0)

		button = Gtk.CheckButton(label=Localize(
			"str_setting_package_list_autocompletion"))
		button.set_active(user_config["editor"]["installs_autocompletion"])
		button.data_path = "editor/installs_autocompletion"
		button.connect("toggled", self.on_settings_toggle)
		settings_box.pack_start(button, False, False, 0)

		button = Gtk.CheckButton(label=Localize(
			"str_setting_select_upgrades_on_startup"))
		button.set_active(user_config["editor"]
						  ["upgrades_selected_by_default"])
		button.data_path = "editor/upgrades_selected_by_default"
		button.connect("toggled", self.on_settings_toggle)
		settings_box.pack_start(button, False, False, 0)

		label = Gtk.Label(
			label="\n" + Localize("str_settings_apt_install_options"))
		label.set_xalign(0)
		settings_box.pack_start(label, False, False, 0)

		button = Gtk.CheckButton(label="Fix missing")
		button.set_active(user_config["apt_install"]["fix_missing"])
		button.data_path = "apt_install/fix_missing"
		button.connect("toggled", self.on_settings_toggle)
		settings_box.pack_start(button, False, False, 0)

		button = Gtk.CheckButton(label="Fix broken")
		button.set_active(user_config["apt_install"]["fix_broken"])
		button.data_path = "apt_install/fix_broken"
		button.connect("toggled", self.on_settings_toggle)
		settings_box.pack_start(button, False, False, 0)

		button = Gtk.CheckButton(label="Fix policy")
		button.set_active(user_config["apt_install"]["fix_policy"])
		button.data_path = "apt_install/fix_policy"
		button.connect("toggled", self.on_settings_toggle)
		settings_box.pack_start(button, False, False, 0)

		notebook.append_page(settings_box, Gtk.Label(
			label=Localize("str_settings")))

		self.sigid_destroy = self.connect("destroy", Gtk.main_quit)
		self.show_all()

	def on_settings_toggle(self, widget):
		global user_config_path
		global user_config

		# Toggle config path
		paths = widget.data_path.split("/")
		conf = user_config
		for p in paths[:-1]:
			conf = conf[p]
		conf[paths[-1]] = widget.get_active()

		# Save config
		with open(user_config_path, 'w') as file:
			yaml.dump(user_config, file)

	def on_lang_changed(self, widget):
		global user_config_path
		global user_config

		tree_iter = widget.get_active_iter()
		if tree_iter is not None:
			model = widget.get_model()
			file = model[tree_iter][1]

			# Save config
			user_config["editor"]["l10n_file"] = file.strip()
			with open(user_config_path, 'w') as file:
				yaml.dump(user_config, file)

			# Display warning
			dialog = Gtk.MessageDialog(
				parent=self,
				flags=0,
				message_type=Gtk.MessageType.WARNING,
				buttons=Gtk.ButtonsType.OK_CANCEL,
				text=Localize("str_confirm_lang_restart")
			)
			response = dialog.run()
			dialog.destroy()

			if response != Gtk.ResponseType.OK:
				return

			# Restart program
			os.execv(sys.executable, [sys.executable] + sys.argv)

	def on_toggle_install(self, widget, path):
		self.list_install[path][0] = not self.list_install[path][0]

	def on_toggle_upgrade(self, widget, path):
		self.list_upgrade[path][0] = not self.list_upgrade[path][0]

	def on_toggle_remove(self, widget, path):
		self.list_remove[path][0] = not self.list_remove[path][0]

	def on_context_install(self, widget, event):
		if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:  # Right-click
			path_info = widget.get_path_at_pos(int(event.x), int(event.y))
			if path_info is not None:
				row, col, cellx, celly = path_info
				widget.grab_focus()
				widget.set_cursor(row, col, 0)

				# Build menu
				menu = Gtk.Menu()

				item = Gtk.MenuItem(label=Localize("str_show_pkg_info"))
				item.data_list = widget.get_model()
				item.connect("activate",
							 self.on_context_apt_package_info, row, False)
				menu.append(item)

				item = Gtk.MenuItem(label=Localize("str_show_pkg_info_raw"))
				item.data_list = widget.get_model()
				item.connect("activate",
							 self.on_context_apt_package_info, row, True)
				menu.append(item)

				item = Gtk.MenuItem(label=Localize("str_remove_from_list"))
				item.data_list = widget.get_model()

				item.connect("activate", lambda _: widget.get_model().remove(
					widget.get_model().get_iter(row)))
				menu.append(item)

				menu.show_all()
				menu.popup_at_pointer(event)

			return True  # stop further handling
		return False

	def on_context_upgrade(self, widget, event):
		if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:  # Right-click
			path_info = widget.get_path_at_pos(int(event.x), int(event.y))
			if path_info is not None:
				row, col, cellx, celly = path_info
				widget.grab_focus()
				widget.set_cursor(row, col, 0)

				# Build menu
				menu = Gtk.Menu()

				item = Gtk.MenuItem(label=Localize("str_show_pkg_info"))
				item.data_list = widget.get_model()
				item.connect("activate",
							 self.on_context_apt_package_info, row, False)
				menu.append(item)

				item = Gtk.MenuItem(label=Localize("str_show_pkg_info_raw"))
				item.data_list = widget.get_model()
				item.connect("activate",
							 self.on_context_apt_package_info, row, True)
				menu.append(item)

				menu.show_all()
				menu.popup_at_pointer(event)

			return True  # stop further handling
		return False

	def on_context_apt_package_info(self, widget, path, viewraw):
		assert widget.data_list
		pkgname = widget.data_list[path][1].strip()
		pkgver = widget.data_list[path][2].strip()
		PackageInfoWindow(pkgname, pkgver, viewraw)

	def lookup_apt_packages(self, prefix: str, grep_terms: list = None):
		prefix = prefix.lower()

		aptcache_proc = subprocess.Popen(
			[*APT_LANG, "apt-cache", "pkgnames", prefix],
			stdout=subprocess.PIPE,
			stderr=subprocess.DEVNULL,
			text=True
		)

		if grep_terms:
			stdout_ = aptcache_proc.stdout
			for term in grep_terms:
				grep_proc = subprocess.Popen(
					["grep", "-i", term],
					stdin=stdout_,
					stdout=subprocess.PIPE,
					stderr=subprocess.DEVNULL,
					text=True
				)
				stdout_ = grep_proc.stdout
			out, _ = grep_proc.communicate()
		else:
			out, _ = aptcache_proc.communicate()

		lines = out.splitlines()
		if not lines:
			return []

		return [line.strip() for line in lines]

	def on_install_entry_activate(self, widget):
		pkgname = widget.get_text().strip()
		# Check if the package exists
		if pkgname in self.lookup_apt_packages(pkgname):
			_, candidate, archs = self.get_package_policy(pkgname)
			for arch in archs:
				# Check that the package:arch is not already listed
				found = False
				for l in self.list_install:
					if l[1] == pkgname and l[3] == arch:
						found = True
						break
				# Add to list
				if not found:
					self.list_install.append([True, pkgname, candidate, arch])
			widget.set_text("")
		else:
			# Red flash
			widget.get_style_context().add_class("error")
			GLib.timeout_add_seconds(0.5,
									 lambda: widget.get_style_context().remove_class("error"))

	def get_package_policy(self, pkgname) -> tuple:
		"""Returns (installed, candidate, archs)"""
		policy = subprocess.run(
			[*APT_LANG, "apt-cache", "policy", pkgname.strip()],
			stdout=subprocess.PIPE,
			stderr=subprocess.DEVNULL,
			text=True
		).stdout.splitlines()

		archs = []
		installed = None
		candidate = None
		for pline in policy:
			pline = pline.strip()
			if pline.startswith("Candidate: "):
				candidate = pline[len("Candidate: "):]
			elif pline.startswith("Installed: "):
				installed = pline[len("Installed: "):]
			elif pline.endswith(" Packages"):
				arch = pline.split()[3].strip()
				if arch not in archs:
					archs.append(arch)

		return installed, candidate, archs

	def get_apt_upgradables(self):
		def worker_():
			proc = subprocess.Popen(
				[*APT_LANG, "apt", "list", "--upgradable"],
				stdout=subprocess.PIPE,
				stderr=subprocess.DEVNULL,
				text=True
			)
			out, _ = proc.communicate()  # waits until process finishes, captures output

			# Clear old rows on main thread
			self.list_upgrade.clear()

			lines = out.splitlines()
			if not lines:
				return

			# Skip "Listing..." header if present
			if lines[0].lower().startswith("listing"):
				lines = lines[1:]

			for line in lines:
				pkgcol = line.strip().split("/", 1)
				pkg = pkgcol[0].strip()

				cols = pkgcol[1].strip().split(" ")

				ver_cad = cols[1].strip() if len(cols) >= 1 else None
				arch = cols[2].strip() if len(cols) >= 2 else None
				ver_ins = cols[5].strip() if len(cols) >= 5 else None

				if ver_cad and ver_ins and arch:
					self.list_upgrade.append([user_config["editor"]["upgrades_selected_by_default"],
											  pkg, ver_cad, ver_ins, arch])

		# Run worker
		threading.Thread(target=worker_, daemon=True).start()

	def get_apt_installed(self):
		def worker_():
			proc = subprocess.Popen(
				[*APT_LANG, "apt", "list", "--installed"],
				stdout=subprocess.PIPE,
				stderr=subprocess.DEVNULL,
				text=True
			)
			out, _ = proc.communicate()  # waits until process finishes, captures output

			# Clear old rows on main thread
			self.list_remove.clear()

			lines = out.splitlines()
			if not lines:
				return

			# Skip "Listing..." header if present
			if lines[0].lower().startswith("listing"):
				lines = lines[1:]

			for line in lines:
				pkgcol = line.strip().split("/", 1)
				pkg = pkgcol[0].strip()

				cols = pkgcol[1].strip().split(" ")

				ver_ins = cols[1].strip() if len(cols) >= 1 else None
				arch = cols[2].strip() if len(cols) >= 2 else None

				if ver_ins and arch:
					self.list_remove.append([False, pkg, ver_ins, arch])

		# Run worker
		threading.Thread(target=worker_, daemon=True).start()

	def do_everything(self, widget):
		apt_installs = [apt_canonicalize_package(row[1], row[2], row[3])
						for row in self.list_install if row[0]]
		apt_upgrades = [apt_canonicalize_package(row[1], row[2], row[4])
						for row in self.list_upgrade if row[0]]
		apt_removes = [apt_canonicalize_package(row[1], row[2], row[3])
					   for row in self.list_remove if row[0]]

		if not apt_installs and not apt_upgrades and not apt_removes:
			# Show MessageDialog
			dialog = Gtk.MessageDialog(
				parent=self,
				flags=0,
				message_type=Gtk.MessageType.INFO,
				buttons=Gtk.ButtonsType.OK,
				text=Localize("str_nothing_to_do")
			)
			dialog.run()
			dialog.destroy()
			return

		# Show confirmation dialog
		dialog = Gtk.MessageDialog(
			parent=self,
			flags=0,
			message_type=Gtk.MessageType.INFO,
			buttons=Gtk.ButtonsType.OK_CANCEL,
			text=Localize("str_summary_of_operations") % (
				len(apt_removes),
				len(apt_installs),
				len(apt_upgrades)
			)
		)
		response = dialog.run()
		dialog.destroy()

		if response != Gtk.ResponseType.OK:
			return

		InstallerWindow(apt_installs, apt_upgrades, apt_removes)
		GLib.idle_add(self.disconnect, self.sigid_destroy)
		GLib.idle_add(self.destroy)


class PackageInfoWindow(Gtk.Window):
	def __init__(self, pkgname, pkgver, viewraw=False, local_pkg=None):
		self.pkgname = pkgname.strip().lower()
		self.pkgver = pkgver.strip().lower()
		self.local_pkg = local_pkg
		self.viewraw = viewraw

		super().__init__(title=Localize("str_pkginfo_title") % self.pkgname)
		self.set_default_size(480, 300)
		self.set_border_width(8)
		self.set_position(Gtk.WindowPosition.CENTER)

		# Create header bar
		header_bar = Gtk.HeaderBar()
		header_bar.set_show_close_button(True)
		header_bar.set_title(Localize("str_pkginfo_title") % self.pkgname)
		self.set_titlebar(header_bar)

		# Add toggle button to header bar
		toggle_button = Gtk.ToggleButton()
		toggle_button.set_active(self.viewraw)
		toggle_button.connect("toggled", self.on_toggle_view)
		image = gtk_image_icon("/usr/share/vapt/images/color-invert-icon.png",
							   24)
		toggle_button.set_image(image)
		toggle_button.set_always_show_image(True)
		header_bar.pack_start(toggle_button)

		# Scrolled window for content
		self.scroll = Gtk.ScrolledWindow()
		self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		self.add(self.scroll)

		# Get package info
		self.list_fields = Gtk.ListStore(str, str)
		self.raw_text = ""
		self.get_package_info()

		# Create both views but only show one
		self.create_views()

		# Show appropriate view
		if viewraw:
			self.show_raw_view()
		else:
			self.show_table_view()

		self.show_all()

	def get_package_info(self):
		"""Get package info and populate both raw text and list fields"""
		# GET INFO
		self.proc = None
		if self.local_pkg is None:
			self.proc = subprocess.Popen(
				# No need for APT_LANG, the output will be readable for the user in their language
				["apt-cache", "show", self.pkgname],
				stdout=subprocess.PIPE,
				stderr=subprocess.DEVNULL,
				text=True
			)
		else:
			self.proc = subprocess.Popen(
				["dpkg-deb", "-I", self.local_pkg],
				stdout=subprocess.PIPE,
				stderr=subprocess.DEVNULL,
				text=True
			)

		out, _ = self.proc.communicate()
		if not out:
			self.show_error("Error getting package info")
			return

		# Process raw text
		blocks = out.strip().split("\n\n")
		for block in blocks:
			if "Version: %s" % self.pkgver in block:
				if self.raw_text != "":
					self.raw_text += "\n\n"
				self.raw_text += block

		# Process for table view
		for block in blocks:
			if "Version: %s" % self.pkgver in block:
				for line in block.splitlines():
					line = line.strip()
					if not line:
						continue

					# Human readable size
					if line.startswith("Installed-Size: "):
						line = line.replace("Installed-Size: ", "").strip()
						num = format_filesize(int(line) * 1024) # KiB to bytes
						line = "Installed-Size: %s" % num


					# Save URLs protocols
					line = line.replace("http://", "http;;//")
					line = line.replace("https://", "http;;//")

					if ':' not in line:
						# Restore URLs
						line = line.replace("http;;//", "http://")
						line = line.replace("https;;//", "http://")
						# Append line to the previous field data
						if self.list_fields and len(self.list_fields) > 0:
							self.list_fields[-1][1] += "\n" + line
						continue

					i_sep = line.index(":")

					# Restore URLs protocols
					line = line.replace("http;;//", "http://")
					line = line.replace("https;;//", "http://")

					field, data = line[:i_sep].strip(), line[i_sep + 1:].strip()
					self.list_fields.append([field, data])

	def create_views(self):
		"""Create both table and raw text views"""
		# Create table view
		self.treeview = Gtk.TreeView(model=self.list_fields)
		column = Gtk.TreeViewColumn(Localize("str_form_field"),
									Gtk.CellRendererText(), text=0)
		column.set_sort_column_id(0)
		self.treeview.append_column(column)
		column = Gtk.TreeViewColumn(Localize("str_form_data"),
									Gtk.CellRendererText(), text=1)
		column.set_sort_column_id(1)
		self.treeview.append_column(column)

		# Create raw text view
		self.textview = Gtk.TextView()
		self.textview.set_editable(False)
		self.textview.set_wrap_mode(Gtk.WrapMode.WORD)
		self.textview.get_buffer().set_text(self.raw_text)

	def show_table_view(self):
		"""Switch to table view"""
		# Remove current content
		for child in self.scroll.get_children():
			self.scroll.remove(child)

		# Add table view
		self.scroll.add(self.treeview)
		self.viewraw = False

		# Refresh display
		self.scroll.show_all()

	def show_raw_view(self):
		"""Switch to raw view"""
		# Remove current content
		for child in self.scroll.get_children():
			self.scroll.remove(child)

		# Add text view
		self.scroll.add(self.textview)
		self.viewraw = True

		# Refresh display
		self.scroll.show_all()

	def on_toggle_view(self, button):
		"""Toggle between raw and table views"""
		if not button.get_active():
			self.show_table_view()
		else:
			self.show_raw_view()

	def show_error(self, message):
		"""Show error message"""
		dialog = Gtk.MessageDialog(
			parent=self,
			flags=0,
			message_type=Gtk.MessageType.INFO,
			buttons=Gtk.ButtonsType.OK,
			text=message
		)
		dialog.run()
		dialog.destroy()

class InstallerWindow(Gtk.Window):
	def __init__(self, list_installs, list_upgrades, list_removes):
		global user_config_path
		global user_config

		super().__init__(title=Localize("str_installer_title"))
		self.set_default_size(480, 0)
		self.set_border_width(16)
		self.set_position(Gtk.WindowPosition.CENTER)

		self.list_installs = list_installs
		self.list_upgrades = list_upgrades
		self.list_removes = list_removes

		vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
		self.add(vbox)

		# Info text
		self.label = Gtk.Label(label="Reading package lists...")
		self.label.set_xalign(0)
		self.label.set_line_wrap(False)
		self.label.set_ellipsize(Pango.EllipsizeMode.END)
		self.label.set_hexpand(True)
		vbox.pack_start(self.label, False, True, 0)

		# Progressbar
		self.progressbar = Gtk.ProgressBar()
		self.progressbar.set_pulse_step(0.05)
		self.progressbar.pulse()
		vbox.pack_start(self.progressbar, False, True, 0)

		# Expandable log area
		expander = Gtk.Expander(label=Localize("str_show_details"))
		expander.set_hexpand(True)
		expander.set_vexpand(True)
		vbox.pack_start(expander, True, True, 0)

		scrolled_window = Gtk.ScrolledWindow()
		scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC,
								   Gtk.PolicyType.AUTOMATIC)
		scrolled_window.set_min_content_height(150)
		scrolled_window.set_hexpand(True)
		scrolled_window.set_vexpand(True)
		expander.add(scrolled_window)

		self.textview = Gtk.TextView()
		self.textview.set_editable(False)
		self.textview.set_wrap_mode(Gtk.WrapMode.NONE)
		self.textview.set_hexpand(True)
		self.textview.set_vexpand(True)
		scrolled_window.add(self.textview)

		self.connect("destroy", self.on_destroy)
		self.show_all()

		# Start worker thread
		self.textbuffer = self.textview.get_buffer()
		threading.Thread(target=self.run_commands, daemon=True).start()

	def update_log(self, text):
		self.label.set_text(text.strip())
		end_iter = self.textbuffer.get_end_iter()
		self.textbuffer.insert(end_iter, text)
		# Scroll to bottom
		mark = self.textbuffer.create_mark(
			None, self.textbuffer.get_end_iter(), False)
		self.textview.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

	def run_commands(self):
		global user_config

		# Step (1) Remove
		if self.list_removes:
			# Build command
			# No need for APT_LANG, the output will be readable for the user in their language
			cmd = [*APT_NONINTERACTIVE, "apt-get", "remove", "-y"]
			cmd.extend(self.list_removes)

			# Run install command
			GLib.idle_add(self.update_log, " ".join(cmd) + "\n")
			self.proc = subprocess.Popen(cmd,
										 stdout=subprocess.PIPE,
										 stderr=subprocess.STDOUT,
										 text=True, bufsize=1)
			for line in self.proc.stdout:
				GLib.idle_add(self.progressbar.pulse)
				if line:
					GLib.idle_add(self.update_log, line)

			self.proc.wait()

		# Step (2) Install & Upgrade
		if self.list_installs or self.list_upgrades:
			# Build command
			# No need for APT_LANG, the output will be readable for the user in their language
			cmd = [*APT_NONINTERACTIVE, "apt-get", "install", "-y"]

			if user_config['apt_install']['fix_missing']:
				cmd.append("--fix-missing")
			if user_config['apt_install']['fix_broken']:
				cmd.append("--fix-broken")
			if user_config['apt_install']['fix_policy']:
				cmd.append("--fix-policy")

			if self.list_installs:
				cmd.extend(self.list_installs)
			if self.list_upgrades:
				cmd.extend(self.list_upgrades)

			# Run install command
			self.proc = subprocess.Popen(cmd,
										 stdout=subprocess.PIPE,
										 stderr=subprocess.STDOUT,
										 text=True, bufsize=1)
			for line in self.proc.stdout:
				GLib.idle_add(self.progressbar.pulse)
				if line:
					GLib.idle_add(self.update_log, line)

			self.proc.wait()

		GLib.idle_add(self.progressbar.set_fraction, 1.0)
		GLib.idle_add(self.label.set_text, Localize("str_done"))
		# GLib.idle_add(self.destroy)

	def on_destroy(self, button):
		if hasattr(self, 'proc') and self.proc and self.proc.poll() is None:
			self.proc.terminate()
		Gtk.main_quit()

class LocalInstallerWindow(Gtk.Window):
	def __init__(self, list_installs, list_reinstalls, quit_on_finnish=False):
		global user_config_path
		global user_config

		super().__init__(title=Localize("str_installer_title"))
		self.set_default_size(480, 0)
		self.set_border_width(16)
		self.set_position(Gtk.WindowPosition.CENTER)

		self.list_installs = list_installs
		self.list_reinstalls = list_reinstalls

		vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
		self.add(vbox)

		# Info text
		self.label = Gtk.Label(label="Reading package lists...")
		self.label.set_xalign(0)
		self.label.set_line_wrap(False)
		self.label.set_ellipsize(Pango.EllipsizeMode.END)
		self.label.set_hexpand(True)
		vbox.pack_start(self.label, False, True, 0)

		# Progressbar
		self.progressbar = Gtk.ProgressBar()
		self.progressbar.set_pulse_step(0.05)
		self.progressbar.pulse()
		vbox.pack_start(self.progressbar, False, True, 0)

		# Expandable log area
		expander = Gtk.Expander(label=Localize("str_show_details"))
		expander.set_hexpand(True)
		expander.set_vexpand(True)
		vbox.pack_start(expander, True, True, 0)

		scrolled_window = Gtk.ScrolledWindow()
		scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC,
								   Gtk.PolicyType.AUTOMATIC)
		scrolled_window.set_min_content_height(150)
		scrolled_window.set_hexpand(True)
		scrolled_window.set_vexpand(True)
		expander.add(scrolled_window)

		self.textview = Gtk.TextView()
		self.textview.set_editable(False)
		self.textview.set_wrap_mode(Gtk.WrapMode.NONE)
		self.textview.set_hexpand(True)
		self.textview.set_vexpand(True)
		scrolled_window.add(self.textview)

		self.connect("destroy", self.on_destroy)
		self.show_all()

		# Start worker thread
		self.textbuffer = self.textview.get_buffer()
		threading.Thread(target=self.run_commands, daemon=True).start()
		if quit_on_finnish:
			self.connect("destroy", Gtk.main_quit)

	def update_log(self, text):
		self.label.set_text(text.strip())
		end_iter = self.textbuffer.get_end_iter()
		self.textbuffer.insert(end_iter, text)
		# Scroll to bottom
		mark = self.textbuffer.create_mark(
			None, self.textbuffer.get_end_iter(), False)
		self.textview.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

	def run_commands(self):
		global user_config

		# Step (1) Installs
		if self.list_installs:
			# Build command
			# No need for APT_LANG, the output will be readable for the user in their language
			cmd = [*APT_NONINTERACTIVE, "apt-get", "install", "-y"]

			if user_config['apt_install']['fix_missing']:
				cmd.append("--fix-missing")
			if user_config['apt_install']['fix_broken']:
				cmd.append("--fix-broken")
			if user_config['apt_install']['fix_policy']:
				cmd.append("--fix-policy")

			if self.list_installs:
				cmd.extend(self.list_installs)

			# Run install command
			GLib.idle_add(self.update_log, " ".join(cmd) + "\n")
			self.proc = subprocess.Popen(cmd,
										 stdout=subprocess.PIPE,
										 stderr=subprocess.STDOUT,
										 text=True, bufsize=1)
			for line in self.proc.stdout:
				GLib.idle_add(self.progressbar.pulse)
				if line:
					GLib.idle_add(self.update_log, line)

			self.proc.wait()

		# Step (2) Reinstalls
		if self.list_reinstalls:
			# Build command
			# No need for APT_LANG, the output will be readable for the user in their language
			cmd = [*APT_NONINTERACTIVE, "apt-get", "install", "-y", "--reinstall"]

			if user_config['apt_install']['fix_missing']:
				cmd.append("--fix-missing")
			if user_config['apt_install']['fix_broken']:
				cmd.append("--fix-broken")
			if user_config['apt_install']['fix_policy']:
				cmd.append("--fix-policy")

			if self.list_reinstalls:
				cmd.extend(self.list_reinstalls)

			# Run install command
			GLib.idle_add(self.update_log, " ".join(cmd) + "\n")
			self.proc = subprocess.Popen(cmd,
										 stdout=subprocess.PIPE,
										 stderr=subprocess.STDOUT,
										 text=True, bufsize=1)
			for line in self.proc.stdout:
				GLib.idle_add(self.progressbar.pulse)
				if line:
					GLib.idle_add(self.update_log, line)

			self.proc.wait()

		GLib.idle_add(self.progressbar.set_fraction, 1.0)
		GLib.idle_add(self.label.set_text, Localize("str_done"))

	def on_destroy(self, button):
		if hasattr(self, 'proc') and self.proc and self.proc.poll() is None:
			self.proc.terminate()

class LocalPackageWindow(Gtk.Window):
	def __init__(self, files):
		super().__init__(title="Install local packages")
		self.set_default_size(640, 480)
		self.set_position(Gtk.WindowPosition.CENTER)

		self.list_installs = []
		self.list_reinstalls = []

		# Main vertical box to hold toolbar (optional) + notebook
		main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
		self.add(main_box)

		# Create a Notebook (tabs)
		big_btn_install = None
		notebook = Gtk.Notebook()
		main_box.pack_start(notebook, True, True, 0)

		# Get data from file
		for deb_file in files:
			if not deb_file or not os.path.isfile(deb_file):
				continue
				# self.exit_error("File '%s' doesn't exists" % deb_file)

			# Check if it's deb package with 'file' command
			proc = subprocess.Popen(
				# No need for APT_LANG, the output will be readable for the user in their language
				["file", "--mime-type", deb_file],
				stdout=subprocess.PIPE,
				stderr=subprocess.DEVNULL,
				text=True
			)
			out, _ = proc.communicate()
			if not out: continue
			if "application/vnd.debian.binary-package" not in out:
				continue
				# self.exit_error("File '%s' is not a .deb package" % deb_file)

			# Get package metadata
			proc = subprocess.Popen(
				# No need for APT_LANG, the output will be readable for the user in their language
				["dpkg-deb", "-I", deb_file],
				stdout=subprocess.PIPE,
				stderr=subprocess.DEVNULL,
				text=True
			)
			PackageInfo, _ = proc.communicate()
			if not PackageInfo: continue

			metadata = {
				"Package": None,
				"Version": None,
				"Architecture": None,
				"Installed-Size": None,
				"Vendor": None,
				"Maintainer": None,
				"Homepage": None,
				"Depends": None
			}
			for line in PackageInfo.split("\n"):
				line = line.strip()
				for key in metadata.keys():
					if line.startswith("%s: " % key):
						value = line[len("%s: " % key):].strip()
						if key == "Installed-Size":
							value = format_filesize(int(value) * 1024) # size is in KiB, so scale to bytes
						if key == "Depends":
							value = ", ".join([d.strip() for d in value.split(",")])
						metadata[key] = value


			# == HEADER ==
			header_box = Gtk.HBox(spacing=12)
			pkg_icon = gtk_gif_icon("/usr/share/vapt/images/loading.gif", 64, 12.0)
			header_box.pack_start(pkg_icon, False, False, 0)

			# Info vertical box
			info_box = Gtk.VBox(spacing=2)
			header_box.pack_start(info_box, True, True, 0)

			# Name (bold)
			label_name = Gtk.Label()
			label_name.set_markup("<b>%s</b>" % metadata['Package'])
			label_name.set_xalign(0)
			info_box.pack_start(label_name, False, False, 0)

			# Version and Arch
			label_ver_arch = Gtk.Label(
				label="%s | %s | %s" % (metadata['Architecture'], metadata['Version'], metadata['Installed-Size'])
			)
			label_ver_arch.set_xalign(0)
			info_box.pack_start(label_ver_arch, False, False, 0)

			# Vendor
			if metadata["Maintainer"]:
				label_vendor = Gtk.Label(label=metadata['Maintainer'])
				label_vendor.set_xalign(0)
				info_box.pack_start(label_vendor, False, False, 0)

			# Homepage (clickable)
			if metadata["Homepage"]:
				homepage_url = metadata["Homepage"]
				label_home = Gtk.Label()
				label_home.set_use_markup(True)
				label_home.set_markup("<a href='%s'>%s</a>" % (homepage_url, homepage_url))
				label_home.set_xalign(0)
				label_home.set_selectable(False)
				# Open browser when clicked
				def on_activate_link(label, uri):
					user = os.environ.get("SUDO_USER")
					if user:
						subprocess.Popen(["sudo", "-u", user, "open", homepage_url],
							stdout=subprocess.DEVNULL,
							stderr=subprocess.DEVNULL
						)
					else:
						subprocess.Popen(["open", homepage_url],
							stdout=subprocess.DEVNULL,
							stderr=subprocess.DEVNULL
						)
					return True  # prevent default handler
				label_home.connect("activate-link", on_activate_link)
				info_box.pack_start(label_home, False, False, 0)

			# Actions vertical box
			actions_box = Gtk.VBox(spacing=2)
			header_box.pack_start(actions_box, False, True, 0)

			# Get installed version
			def get_installed_version(pkgname: str) -> str | None:
				"""Return installed version of package or None if not installed."""
				proc = subprocess.run(
					["dpkg-query", "-W", "-f=${Status} ${Version}", pkgname],
					stdout=subprocess.PIPE,
					stderr=subprocess.DEVNULL,
					text=True
				)

				if proc.returncode != 0:
					return None

				output = proc.stdout.strip()

				# Installed packages contain:
				# "install ok installed <version>"
				if output.startswith("install ok installed"):
					return output.split()[-1]

				return None

			# Check "Install" or "Upgrade" or "Reinstall"
			is_reinstall = False
			installed_version = get_installed_version(metadata["Package"])
			if installed_version is None:
				action_label = "Install package"
				self.list_installs.append(deb_file)
			elif installed_version == metadata["Version"]:
				action_label = "Reinstall package"
				is_reinstall = True
				self.list_reinstalls.append(deb_file)
			else:
				action_label = "Upgrade package"
				self.list_installs.append(deb_file)

			button = Gtk.Button(label=action_label)
			def on_install(button, deb_file):
				# Prevent double install
				if not button.get_sensitive(): return
				# Deactivate button
				button.set_sensitive(False)

				# Install package
				LocalInstallerWindow(
					[deb_file] if not is_reinstall else None,
					[deb_file] if is_reinstall else None)

				# Deactivate button
				if is_reinstall:
					self.list_reinstalls.remove(deb_file)
				else:
					self.list_installs.remove(deb_file)

				pkg_count = len(self.list_installs) + len(self.list_reinstalls)
				if big_btn_install is not None:
					big_btn_install.set_label("Install (%d) package(s)" % pkg_count)
					if pkg_count == 0:
						big_btn_install.set_sensitive(False)
				return

			button.connect("clicked", on_install, deb_file)
			actions_box.pack_start(button, False, False, 0)

			button = Gtk.Button(label="Details")
			button.connect("clicked", self.on_details, deb_file, metadata)
			actions_box.pack_start(button, False, False, 0)

			# == TAB CONTENT ==
			tab_box = Gtk.VBox(spacing=6)
			tab_box.set_border_width(16)
			tab_box.pack_start(header_box, False, False, 0)
			notebook2 = Gtk.Notebook()
			tab_box.pack_start(notebook2, True, True, 0)

			# == Fetch control files ==
			temp_folder = mkdtemp()
			proc = subprocess.Popen(
				["dpkg-deb", "-e", deb_file, temp_folder],
				stdout=subprocess.PIPE,
				stderr=subprocess.DEVNULL
			)
			proc.communicate()

			# When program exits, remove temp folder
			atexit.register(rmforce, temp_folder)

			# Create a horizontal paned container to split left and right
			control_paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
			control_paned.set_position(128) # Set initial divider position

			# Create a TreeStore for hierarchical files
			control_list_files = Gtk.ListStore(str, str)
			control_list_files.set_sort_column_id(0, Gtk.SortType.ASCENDING)
			# Append all control files inside the temp folder
			for control_file in os.listdir(temp_folder):
				with open(os.path.join(temp_folder, control_file), "r") as f:
					control_list_files.append([control_file, f.read()])

			# Create TreeView for hierarchical display
			control_files = Gtk.TreeView(model=control_list_files)
			control_files.set_hexpand(True)
			control_files.set_vexpand(True)

			renderer = Gtk.CellRendererText()
			column = Gtk.TreeViewColumn("File", renderer, text=0)
			control_files.append_column(column)

			scroll_files = Gtk.ScrolledWindow()
			scroll_files.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
			scroll_files.set_hexpand(True)
			scroll_files.set_vexpand(True)

			scroll_files.add(control_files)
			control_paned.add1(scroll_files)

			# Right panel: Text view for file content
			scroll_files = Gtk.ScrolledWindow()
			scroll_files.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

			content_textview = Gtk.TextView()
			content_textview.set_editable(False)
			content_textview.set_wrap_mode(Gtk.WrapMode.WORD)
			content_textview.set_monospace(True)

			scroll_files.add(content_textview)

			control_paned.add2(scroll_files)

			# Connect selection changed signal
			def on_control_file_selected(selection, list_store, textview):
				"""Callback when a control file is selected in the treeview"""
				model, treeiter = selection.get_selected()
				if treeiter is not None:
					# Get the content from the second column
					content = model[treeiter][1]
					textview.get_buffer().set_text(content)

			control_files.get_selection().connect("changed", on_control_file_selected, control_list_files, content_textview)

			notebook2.append_page(control_paned, Gtk.Label(label="Control files"))

			# == Fetch contents of the package ==
			# Create a TreeStore for hierarchical files
			file_tree_store = Gtk.TreeStore(str, str)
			file_tree_store.set_sort_column_id(0, Gtk.SortType.ASCENDING)

			# Create TreeView for hierarchical display
			treeview_files = Gtk.TreeView(model=file_tree_store)
			treeview_files.set_hexpand(True)
			treeview_files.set_vexpand(True)

			renderer = Gtk.CellRendererText()
			column = Gtk.TreeViewColumn("Path", renderer, text=0)
			treeview_files.append_column(column)

			renderer = Gtk.CellRendererText()
			column = Gtk.TreeViewColumn("Size", renderer, text=1)
			treeview_files.append_column(column)

			# Scrollable container
			scroll_files = Gtk.ScrolledWindow()
			scroll_files.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
			scroll_files.set_hexpand(True)
			scroll_files.set_vexpand(True)
			scroll_files.add(treeview_files)
			notebook2.append_page(scroll_files, Gtk.Label(label="Contents"))

			# == Get file list asynchronously ==
			# Helper to insert paths into tree recursively
			def insert_path(tree_store, path: str, size: int):
				# If path contains " -> ", don't split after it
				path_s = path
				path_e = None
				symidx = path.find(" -> ")
				if symidx != -1:
					symidx = path.rfind("/", 0, symidx) + 1
					path_s = path[:symidx]
					path_e = path[symidx:]
				parts = path_s.strip("/").split("/")
				if path_e is not None: parts.append(path_e)

				parent = None
				current_store = tree_store
				for i, part in enumerate(parts):
					# Check if this node already exists under parent
					exists = False
					iter_ = current_store.get_iter_first() if parent is None else current_store.iter_children(parent)
					while iter_:
						if current_store[iter_][0] == part:
							exists = True
							parent = iter_
							# Remove size from folders
							current_store[iter_][1] = ""
							break
						iter_ = current_store.iter_next(iter_)
					if not exists:
						# Create new node
						new_iter = current_store.append(parent, [part, format_filesize(size)])
						parent = new_iter

			def fill_files(deb_file, tree_store, _pkg_icon):
				# Run dpkg -c to get file paths
				_deb_files = []
				try:
					proc = subprocess.Popen(
						["dpkg-deb", "-c", deb_file],
						stdout=subprocess.PIPE,
						stderr=subprocess.DEVNULL,
						text=True
					)
					out, _ = proc.communicate()

					for line in out.splitlines():
						# dpkg -c outputs lines like:
						# -rw-r--r-- root/root       1234 2026-01-15 12:34 ./usr/bin/example -> /usr/share/example/example
						parts = re.sub(r'\s+', ' ', line).split()
						if len(parts) >= 6:
							filesize = int(parts[2])
							filepath = " ".join(parts[5:])
							_deb_files.append(filepath)
							GLib.idle_add(insert_path, tree_store, filepath, filesize)
				except Exception as e:
					print(e.with_traceback(None))
					GLib.idle_add(tree_store.append, None, ["Error reading package"])
				finally:
					# Find the most probable icon
					if _deb_files is None or len(_deb_files) == 0:
						return None

					icon = None
					img_formats = [".png", ".jpg", ".jpeg", ".bmp", ".svg"]

					tmpf = mkdtemp()
					atexit.register(rmforce, tmpf)

					deb_desktop_files = [d for d in _deb_files if d.endswith(".desktop")]
					if len(deb_desktop_files) > 0:
						for df in deb_desktop_files:
							# Extract one file in memory
							p1 = subprocess.Popen(
								["dpkg-deb", "--fsys-tarfile", deb_file],
								stdout=subprocess.PIPE,
								stderr=subprocess.DEVNULL
							)
							p2 = subprocess.Popen(
								["tar", "-xO", df],
								stdin=p1.stdout,
								stdout=subprocess.PIPE,
								stderr=subprocess.DEVNULL
							)
							# Important: allow proper pipe shutdown
							p1.stdout.close()
							output, _ = p2.communicate()
							p1.wait()
							# Read the file and find "Icon"
							desktop_content = output.decode("utf-8")
							for line in desktop_content.splitlines():
								if line.startswith("Icon="):
									icon = line[5:].strip()
									break

					def icon_score(path: str) -> int:
						score = 0
						p = path.lower()

						# Prefer hicolor theme
						if "/hicolor/" in p:
							score += 50

						# Prefer scalable icons
						if "/scalable/" in p:
							score += 40

						# Prefer larger size directories (e.g. 256x256 > 128x128 > 64x64)
						m = re.search(r'/(\d+)x\1/', p)
						if m:
							score += int(m.group(1))

						# Slight preference for PNG over others
						if p.endswith(".png"):
							score += 10

						return score

					def icon_update(path: str) -> None:
						# Extract image file
						iconfile_path = os.path.join(tmpf, "iconfile")
						with open(iconfile_path, "wb") as f:
							p1 = subprocess.Popen(
								["dpkg-deb", "--fsys-tarfile", deb_file],
								stdout=subprocess.PIPE,
								stderr=subprocess.DEVNULL
							)
							p2 = subprocess.Popen(
								["tar", "-xO", path],
								stdin=p1.stdout,
								stdout=subprocess.PIPE,
								stderr=subprocess.DEVNULL
							)
							# Important: allow proper pipe shutdown
							p1.stdout.close()
							output, _ = p2.communicate()
							p1.wait()
							f.write(output)

						# Update GTK image
						gtk_image = GdkPixbuf.Pixbuf.new_from_file_at_scale(
							filename=iconfile_path,
							width=64, height=64,
							preserve_aspect_ratio=True
						)
						GLib.idle_add(_pkg_icon.set_from_pixbuf, gtk_image)

					if icon:
						# Icons found, use the first one
						if icon.startswith("/"):
							# Easy, it's an absolute path inside the package
							icon = "." + icon
						else:
							# Check if file has one of the supported formats
							raw_look = False
							for fmt in img_formats:
								if icon.endswith(fmt):
									raw_look = True
									break

							if raw_look:
								possible_icons = [d for d in _deb_files if d.endswith(icon)]
							else:
								# Try searching the Icon in some common image folders
								possible_icons = []
								for fmt in img_formats:
									possible_icons += [d for d in _deb_files if d.endswith(icon + fmt)]

							# Select the most probable icon from possible_icons
							possible_icons.sort(key=icon_score, reverse=True)
							icon = possible_icons[0]

						icon_update(icon)
						return

					# Desktop files do not provide any icon,
					# use the default icon
					gtk_image = GdkPixbuf.Pixbuf.new_from_file_at_scale(
						filename="/usr/share/vapt/images/application-x-deb.png",
						width=64, height=64,
						preserve_aspect_ratio=True
					)
					GLib.idle_add(_pkg_icon.set_from_pixbuf, gtk_image)
					return

			# Start the thread
			thread = threading.Thread(target=fill_files, args=[deb_file, file_tree_store, pkg_icon], daemon=True).start()

			notebook.append_page(tab_box, Gtk.Label(label=metadata["Package"]))

		pkg_count = len(self.list_installs) + len(self.list_reinstalls)
		if pkg_count > 1:
			big_btn_install = Gtk.Button(label="Install (%d) package(s)" % pkg_count)
			big_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
			big_btn_box.set_border_width(6)
			big_btn_box.pack_start(big_btn_install, True, True, 8)

			def on_big_install(button):
				# Show confirmation dialog
				dialog = Gtk.MessageDialog(
					parent=self,
					flags=0,
					message_type=Gtk.MessageType.INFO,
					buttons=Gtk.ButtonsType.OK_CANCEL,
					text=Localize("Summary:\n- Install %d packages\n- Reinstall %d packages") % (
						len(self.list_installs),
						len(self.list_reinstalls)
					)
				)
				response = dialog.run()
				dialog.destroy()
				if response != Gtk.ResponseType.OK:
					return

				GLib.idle_add(self.disconnect, self.sigid_destroy)
				LocalInstallerWindow(self.list_installs,
					self.list_reinstalls,
					quit_on_finnish=True)
				GLib.idle_add(self.destroy)

			big_btn_install.connect("clicked", on_big_install)

			main_box.pack_start(big_btn_box, False, True, 0)

		self.sigid_destroy = self.connect("destroy", Gtk.main_quit)
		self.show_all()

	def on_details(self, button, file, metadata):
		PackageInfoWindow(metadata["Package"], metadata["Version"], False, local_pkg=file)

	def exit_error(self, msg):
		# Show MessageDialog
		dialog = Gtk.MessageDialog(
			parent=self,
			flags=0,
			message_type=Gtk.MessageType.ERROR,
			buttons=Gtk.ButtonsType.OK,
			text=msg
		)
		dialog.run()
		dialog.destroy()
		self.destroy()
		sys.exit(1)


class UpdaterWindow(Gtk.Window):
	def __init__(self):
		super().__init__(title=Localize("str_updater_title"))
		self.set_default_size(480, 0)
		self.set_border_width(16)
		self.set_position(Gtk.WindowPosition.CENTER)

		vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
		self.add(vbox)

		# Info text
		self.label = Gtk.Label(label="Updating package database...")
		self.label.set_xalign(0)
		self.label.set_line_wrap(False)
		self.label.set_ellipsize(Pango.EllipsizeMode.END)
		self.label.set_hexpand(True)
		vbox.pack_start(self.label, False, True, 0)

		# Progressbar
		self.progressbar = Gtk.ProgressBar()
		self.progressbar.set_pulse_step(0.05)
		self.progressbar.pulse()
		vbox.pack_start(self.progressbar, False, True, 0)

		# Expandable log area
		expander = Gtk.Expander(label=Localize("str_show_details"))
		expander.set_hexpand(True)
		expander.set_vexpand(True)
		vbox.pack_start(expander, True, True, 0)

		scrolled_window = Gtk.ScrolledWindow()
		scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC,
								   Gtk.PolicyType.AUTOMATIC)
		scrolled_window.set_min_content_height(150)
		scrolled_window.set_hexpand(True)
		scrolled_window.set_vexpand(True)
		expander.add(scrolled_window)

		self.textview = Gtk.TextView()
		self.textview.set_editable(False)
		self.textview.set_wrap_mode(Gtk.WrapMode.NONE)
		self.textview.set_hexpand(True)
		self.textview.set_vexpand(True)
		scrolled_window.add(self.textview)

		self.sigid_destroy = self.connect("destroy", self.on_destroy)
		self.show_all()

		# Start worker thread
		self.textbuffer = self.textview.get_buffer()
		threading.Thread(target=self.run_command, daemon=True).start()

	def update_log(self, text):
		self.label.set_text(text.strip())
		end_iter = self.textbuffer.get_end_iter()
		self.textbuffer.insert(end_iter, text)
		# Scroll to bottom
		mark = self.textbuffer.create_mark(None, self.textbuffer.get_end_iter(),
										   False)
		self.textview.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

	def run_command(self):
		# No need for APT_LANG, the output will be readable for the user in their language
		cmd = [*APT_NONINTERACTIVE, "apt-get", "update", "-y"]
		GLib.idle_add(self.update_log, " ".join(cmd) + "\n")
		self.proc = subprocess.Popen(
			cmd,
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True, bufsize=1
		)

		for line in self.proc.stdout:
			GLib.idle_add(self.progressbar.pulse)
			if line:
				GLib.idle_add(self.update_log, line)

		# Check return code
		self.proc.wait()
		if self.proc.returncode != 0:
			GLib.idle_add(self.progressbar.set_fraction, 1.0)
			GLib.idle_add(self.label.set_text, Localize("str_error"))
			return

		GLib.idle_add(self.progressbar.set_fraction, 1.0)
		GLib.idle_add(self.label.set_text, Localize("str_done"))

		GLib.idle_add(self.disconnect, self.sigid_destroy)
		GLib.idle_add(self.open_main_window)
		GLib.idle_add(self.destroy)

	def on_destroy(self, button):
		if hasattr(self, 'proc') and self.proc and self.proc.poll() is None:
			self.proc.terminate()
		Gtk.main_quit()

	def open_main_window(self):
		MainWindow()


def show_about_dialog():
	about_dialog = Gtk.AboutDialog()
	about_dialog.set_program_name("vapt")
	about_dialog.set_version("v1.1")
	about_dialog.set_comments(
		"Visual APT Manager is a simple GUI for APT package management")
	about_dialog.set_website("https://github.com/bruneo32/vapt")
	about_dialog.set_authors(["Bruno Castro Garcia <bruneo32b@gmail.com>"])
	about_dialog.set_license_type(Gtk.License.MIT_X11)
	about_dialog.set_logo_icon_name("gartoon-system-upgrade")
	about_dialog.run()
	about_dialog.destroy()

# ==== MAIN ==== #


def is_valid_l10n_file(yml: dict) -> bool:
	locales = yml.get('locales', [])
	strings = yml.get('strings', {})
	displayName = yml.get('displayName', "")
	return locales and strings and displayName


if __name__ == "__main__":
	# Load config
	if os.path.isfile(user_config_path):
		with open(user_config_path, 'r', encoding="utf-8") as file:
			user_config = yaml.safe_load(file)

	# Load fallback l10n
	if not os.path.exists(master_lang_file_path):
		print("Default language file doesn't exists: %s." %
			  master_lang_file_path, file=sys.stderr)
		sys.exit(1)
	with open(master_lang_file_path, mode="r", encoding="utf-8") as f:
		yml = yaml.safe_load(f)
		if not is_valid_l10n_file(yml):
			print("Malformed default language file: %s." %
				  master_lang_file_path, file=sys.stderr)
			sys.exit(1)
		l10n_strings_master = yml.get('strings', {})

	# Load user localization
	os_lang = os.environ.get("LANG", "en_US.UTF-8")
	gtk_lang = os_lang
	lang_files = glob.glob("/usr/share/vapt/l10n/*.yml", recursive=True)
	user_lang_override = user_config["editor"]["l10n_file"]

	# Search for a file supporting this locale
	found = False if user_lang_override == "" else True
	for lang_file in lang_files:
		with open(lang_file, mode="r", encoding="utf-8") as f:
			yml = yaml.safe_load(f)
			if not is_valid_l10n_file(yml):
				continue

			# Save for combobox
			langs_available.append(
				{"display": yml.get('displayName', ""), "file": lang_file})

			# Check if it's the user override
			if user_lang_override == lang_file:
				lang_file_path = lang_file
				gtk_lang = yml.get('locales', [os_lang])[0]
				l10n_strings = yml.get('strings', {})

			# If found, skip
			if found:
				continue

			# Check that locale is supported by this file
			for locale in yml.get('locales', []):
				if locale in os_lang:
					lang_file_path = lang_file
					l10n_strings = yml.get('strings', {})
					found = True
					break

	if lang_file_path is None:
		if user_lang_override != "":
			print("Could not find language file: %s" %
				  user_lang_override, file=sys.stderr)
			l10n_strings = l10n_strings_master
		print("Could not find language file supporting locale: %s" %
			  os_lang, file=sys.stderr)
		l10n_strings = l10n_strings_master

	# Set system lang label
	langs_available[0]["display"] = Localize("str_settings_language_default")

	# Set localization for GTK process (OK_CANCEL, ABOUT, etc.)
	os.environ["LANGUAGE"] = gtk_lang
	os.environ["LC_MESSAGES"] = gtk_lang
	os.environ["LANG"] = gtk_lang
	Gtk.init([])

	# Check if opened a file as argument
	if len(sys.argv) > 1:
		LocalPackageWindow(sys.argv[1:])
	else:
		# Launch first window
		UpdaterWindow()
	Gtk.main()
