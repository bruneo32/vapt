#!/usr/bin/env python3
import gi, subprocess, threading, yaml, os.path
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk, Pango

user_config_path = os.path.expandvars("$VAPT_CONFIG_PATH") or os.path.expandvars("$HOME/.config/vapt.yml")
os.makedirs(os.path.dirname(user_config_path), exist_ok=True)

user_config = {
	'editor': {
		'installs_autocompletion': True,
		'upgrades_selected_by_default': True,
	},
 	'apt_install': {
		'fix_missing': True,
		'fix_broken': True,
		'fix_policy': False
	}
}

class MainWindow(Gtk.Window):
	def __init__(self):
		global user_config_path
		global user_config

		# Load config
		if os.path.isfile(user_config_path):
			with open(user_config_path, 'r') as file:
				user_config = yaml.safe_load(file)

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
			["bash", "-c", "echo \"$(grep '^PRETTY_NAME=' /etc/os-release | cut -d= -f2 | tr -d '\"')\""],
			stdout=subprocess.PIPE,
			stderr=subprocess.DEVNULL,
			text=True
		)
		os_name, _ = proc.communicate()
		os_name = os_name.strip() or "Unknown OS"

		proc = subprocess.Popen(
			["dpkg", "--print-architecture"],
			stdout=subprocess.PIPE,
			stderr=subprocess.DEVNULL,
			text=True
		)
		dpkg_arch, _ = proc.communicate()
		dpkg_arch = dpkg_arch.strip() or "N/A"

		label = Gtk.Label(label=os_name)
		btn_box.pack_start(label, False, False, 0)

		label = Gtk.Label(label="  " + dpkg_arch)
		#label.modify_font(Pango.FontDescription("Bold"))
		btn_box.pack_start(label, False, False, 0)

		# expanding spacer pushes following children to the right
		spacer = Gtk.Box()
		spacer.set_hexpand(True)
		btn_box.pack_start(spacer, True, True, 0)

		button = Gtk.Button(label="Quit")
		button.set_halign(Gtk.Align.END)
		button.connect("clicked", lambda button: self.destroy())
		btn_box.pack_start(button, False, False, 0)

		button = Gtk.Button(label="Install")
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
		entry.set_placeholder_text("Search for a package...")
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

		render_toggle = Gtk.CellRendererToggle()
		render_toggle.connect("toggled", self.on_toggle_install)
		column = Gtk.TreeViewColumn("Install", render_toggle, active=0)
		column.set_sort_column_id(0)
		treeview.append_column(column)

		column = Gtk.TreeViewColumn("Package Name", Gtk.CellRendererText(), text=1)
		column.set_sort_column_id(1)
		treeview.append_column(column)
		column = Gtk.TreeViewColumn("Candidate Version", Gtk.CellRendererText(), text=2)
		column.set_sort_column_id(2)
		treeview.append_column(column)
		column = Gtk.TreeViewColumn("Architecture", Gtk.CellRendererText(), text=3)
		column.set_sort_column_id(3)
		treeview.append_column(column)

		treeview.connect("button-press-event", self.on_context_install)

		install_scroll = Gtk.ScrolledWindow()
		install_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		install_scroll.add(treeview)
		paned.pack_start(install_scroll, True, True, 0)

		# Put paned into notebook tab
		tab1_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		tab1_box.pack_start(paned, True, True, 0)
		notebook.append_page(tab1_box, Gtk.Label(label="Install"))

		# -----------------------
		# Tab 2: Upgrade
		# -----------------------
		self.list_upgrade = Gtk.ListStore(bool, str, str, str, str)
		self.get_apt_upgradables()

		treeview = Gtk.TreeView(model=self.list_upgrade)

		render_toggle = Gtk.CellRendererToggle()
		render_toggle.connect("toggled", self.on_toggle_upgrade)
		column = Gtk.TreeViewColumn("Install", render_toggle, active=0)
		column.set_sort_column_id(0)
		treeview.append_column(column)

		column = Gtk.TreeViewColumn("Package Name", Gtk.CellRendererText(), text=1)
		column.set_sort_column_id(1)
		treeview.append_column(column)
		column = Gtk.TreeViewColumn("Candidate Version", Gtk.CellRendererText(), text=2)
		column.set_sort_column_id(2)
		treeview.append_column(column)
		column = Gtk.TreeViewColumn("Installed Version", Gtk.CellRendererText(), text=3)
		column.set_sort_column_id(3)
		treeview.append_column(column)
		column = Gtk.TreeViewColumn("Architecture", Gtk.CellRendererText(), text=4)
		column.set_sort_column_id(4)
		treeview.append_column(column)

		treeview.connect("button-press-event", self.on_context_upgrade)

		upgrade_scroll = Gtk.ScrolledWindow()
		upgrade_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		upgrade_scroll.add(treeview)

		notebook.append_page(upgrade_scroll, Gtk.Label(label="Upgrade"))

		# -----------------------
		# Tab 3: Settings
		# -----------------------
		settings_box = Gtk.VBox()
		settings_box.set_border_width(16)
		settings_box.set_spacing(6)

		label = Gtk.Label(label="Editor")
		label.set_xalign(0)
		settings_box.pack_start(label, False, False, 0)

		button = Gtk.CheckButton(label="Package list autocompletion")
		button.set_active(user_config["editor"]["installs_autocompletion"])
		button.data_path = "editor/installs_autocompletion"
		button.connect("toggled", self.on_settings_toggle)
		settings_box.pack_start(button, False, False, 0)

		button = Gtk.CheckButton(label="Upgrades selected by default")
		button.set_active(user_config["editor"]["upgrades_selected_by_default"])
		button.data_path = "editor/upgrades_selected_by_default"
		button.connect("toggled", self.on_settings_toggle)
		settings_box.pack_start(button, False, False, 0)

		label = Gtk.Label(label="\nInstall options")
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

		notebook.append_page(settings_box, Gtk.Label(label="Settings"))

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

	def on_toggle_install(self, widget, path):
		self.list_install[path][0] = not self.list_install[path][0]

	def on_toggle_upgrade(self, widget, path):
		self.list_upgrade[path][0] = not self.list_upgrade[path][0]

	def on_context_install(self, widget, event):
		if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:  # Right-click
			path_info = widget.get_path_at_pos(int(event.x), int(event.y))
			if path_info is not None:
				row, col, cellx, celly = path_info
				widget.grab_focus()
				widget.set_cursor(row, col, 0)

				# Build menu
				menu = Gtk.Menu()

				item = Gtk.MenuItem(label="Show package info")
				item.data_list = widget.get_model()
				item.connect("activate", self.on_context_apt_package_info, row, False)
				menu.append(item)

				item = Gtk.MenuItem(label="Show package info (raw)")
				item.data_list = widget.get_model()
				item.connect("activate", self.on_context_apt_package_info, row, True)
				menu.append(item)

				item = Gtk.MenuItem(label="Remove from list")
				item.data_list = widget.get_model()

				item.connect("activate", lambda _: widget.get_model().remove(widget.get_model().get_iter(row)))
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

				item = Gtk.MenuItem(label="Show package info")
				item.data_list = widget.get_model()
				item.connect("activate", self.on_context_apt_package_info, row, False)
				menu.append(item)

				item = Gtk.MenuItem(label="Show package info (raw)")
				item.data_list = widget.get_model()
				item.connect("activate", self.on_context_apt_package_info, row, True)
				menu.append(item)

				menu.show_all()
				menu.popup_at_pointer(event)

			return True  # stop further handling
		return False

	def on_context_apt_package_info(self, widget, path, viewraw):
		assert widget.data_list
		pkgname = widget.data_list[path][1].strip()
		pkgver  = widget.data_list[path][2].strip()
		PackageInfoWindow(pkgname, pkgver, viewraw)

	def lookup_apt_packages(self, prefix: str, grep_terms: list = None):
		prefix = prefix.lower()

		aptcache_proc = subprocess.Popen(
			["apt-cache", "pkgnames", prefix],
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
		if not lines: return []

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
			GLib.timeout_add_seconds(0.5, lambda: widget.get_style_context().remove_class("error"))

	def get_package_policy(self, pkgname) -> tuple:
		"""Returns (installed, candidate, archs)"""
		policy = subprocess.run(
			["apt-cache", "policy", pkgname.strip()],
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
				["apt", "list", "--upgradable"],
				stdout=subprocess.PIPE,
				stderr=subprocess.DEVNULL,
				text=True
			)
			out, _ = proc.communicate()  # waits until process finishes, captures output

			# Clear old rows on main thread
			self.list_upgrade.clear()

			lines = out.splitlines()
			if not lines: return

			# Skip "Listing..." header if present
			if lines[0].lower().startswith("listing"):
				lines = lines[1:]

			for line in lines:
				pkgcol = line.strip().split("/", 1)
				pkg = pkgcol[0].strip()

				cols = pkgcol[1].strip().split(" ")

				ver_cad = cols[1].strip() if len(cols) >= 1 else None
				arch    = cols[2].strip() if len(cols) >= 2 else None
				ver_ins = cols[5].strip() if len(cols) >= 5 else None

				if ver_cad and ver_ins and arch:
					self.list_upgrade.append([user_config["editor"]["upgrades_selected_by_default"],
											 pkg, ver_cad, ver_ins, arch])

		# Run worker
		threading.Thread(target=worker_, daemon=True).start()

	def do_everything(self, widget):
		apt_installs = [f'{row[1]}:{row[3]}={row[2]}' for row in self.list_install if row[0]]
		apt_upgrades = [f'{row[1]}:{row[4]}={row[2]}' for row in self.list_upgrade if row[0]]

		if not apt_installs and not apt_upgrades:
			# Show MessageDialog
			dialog = Gtk.MessageDialog(
				parent=self,
				flags=0,
				message_type=Gtk.MessageType.INFO,
				buttons=Gtk.ButtonsType.OK,
				text="Nothing to do."
			)
			dialog.run()
			dialog.destroy()
			return

		InstallerWindow(apt_installs, apt_upgrades)
		GLib.idle_add(self.disconnect, self.sigid_destroy)
		GLib.idle_add(self.destroy)

class PackageInfoWindow(Gtk.Window):
	def __init__(self, pkgname, pkgver, viewraw=False):
		self.pkgname = pkgname.strip().lower()
		self.pkgver  = pkgver.strip().lower()

		super().__init__(title="Package info: {pkgname}".format(pkgname=self.pkgname))
		self.set_default_size(480, 300)
		self.set_border_width(8)
		self.set_position(Gtk.WindowPosition.CENTER)

		scroll = Gtk.ScrolledWindow()
		scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		self.add(scroll)

		list_fields = Gtk.ListStore(str, str)

		# GET INFO
		proc = subprocess.Popen(
			["apt-cache", "show", self.pkgname],
			stdout=subprocess.PIPE,
			stderr=subprocess.DEVNULL,
			text=True
		)
		out, _ = proc.communicate()
		if not out: return

		if viewraw: res_txt = ""

		# Filter stanzas
		blocks = out.strip().split("\n\n")
		for block in blocks:
			if "Version: {pkgver}".format(pkgver=self.pkgver) in block:
				# Requested package version
				if viewraw:
					if res_txt != "": res_txt += "\n\n"
					res_txt += block
					continue

				# Add fields to table
				for line in block.splitlines():
					line = line.strip()
					if not line: continue

					# Save URLs protocols
					line = line.replace("http://", "http;;//")
					line = line.replace("https://", "http;;//")

					if ':' not in line:
						# Restore URLs
						line = line.replace("http;;//", "http://")
						line = line.replace("https;;//", "http://")
						# Append line to the previous field data
						if list_fields:
							list_fields[-1][1] += "\n" + line
						continue

					i_sep = line.index(":")

					# Restore URLs protocols
					line = line.replace("http;;//", "http://")
					line = line.replace("https;;//", "http://")

					field,data = line[:i_sep].strip(), line[i_sep + 1:].strip()
					list_fields.append([field,data])

		if viewraw:
			# Info text
			textview = Gtk.TextView()
			textview.set_editable(False)
			textview.get_buffer().set_text(res_txt)
			# textview.set_wrap_mode(Gtk.WrapMode.WORD)
			scroll.add(textview)
		else:
			# Info table
			treeview = Gtk.TreeView(model=list_fields)

			column = Gtk.TreeViewColumn("Field", Gtk.CellRendererText(), text=0)
			column.set_sort_column_id(0)
			treeview.append_column(column)
			column = Gtk.TreeViewColumn("Data", Gtk.CellRendererText(), text=1)
			column.set_sort_column_id(1)
			treeview.append_column(column)
			scroll.add(treeview)

		self.show_all()

class InstallerWindow(Gtk.Window):
	def __init__(self, list_installs, list_upgrades):
		global user_config_path
		global user_config

		super().__init__(title="Installing packages")
		self.set_default_size(480, 0)
		self.set_border_width(16)
		self.set_position(Gtk.WindowPosition.CENTER)

		self.list_installs = list_installs
		self.list_upgrades = list_upgrades

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
		expander = Gtk.Expander(label="Show details")
		expander.set_hexpand(True)
		expander.set_vexpand(True)
		vbox.pack_start(expander, True, True, 0)

		scrolled_window = Gtk.ScrolledWindow()
		scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
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
		mark = self.textbuffer.create_mark(None, self.textbuffer.get_end_iter(), False)
		self.textview.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

	def run_commands(self):
		global user_config

		# Build command
		cmd = ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y"]

		if user_config['apt_install']['fix_missing']: cmd.append("--fix-missing")
		if user_config['apt_install']['fix_broken']:  cmd.append("--fix-broken")
		if user_config['apt_install']['fix_policy']:  cmd.append("--fix-policy")

		if self.list_installs: cmd.extend(self.list_installs)
		if self.list_upgrades: cmd.extend(self.list_upgrades)

		# Run install command
		self.proc = subprocess.Popen(cmd,
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True, bufsize=1
		)
		for line in self.proc.stdout:
			GLib.idle_add(self.progressbar.pulse)
			if line: GLib.idle_add(self.update_log, line)

		self.proc.wait()
		GLib.idle_add(self.progressbar.set_fraction, 1.0)
		GLib.idle_add(self.label.set_text, "Done.")

		# GLib.idle_add(self.destroy)

	def on_destroy(self, button):
		if hasattr(self, 'proc') and self.proc and self.proc.poll() is None:
			self.proc.terminate()
		Gtk.main_quit()

class UpdaterWindow(Gtk.Window):
	def __init__(self):
		super().__init__(title="Checking updates")
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
		expander = Gtk.Expander(label="Show details")
		expander.set_hexpand(True)
		expander.set_vexpand(True)
		vbox.pack_start(expander, True, True, 0)

		scrolled_window = Gtk.ScrolledWindow()
		scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
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
		mark = self.textbuffer.create_mark(None, self.textbuffer.get_end_iter(), False)
		self.textview.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

	def run_command(self):
		self.proc = subprocess.Popen(
			["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update", "-y"],
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True, bufsize=1
		)

		for line in self.proc.stdout:
			GLib.idle_add(self.progressbar.pulse)
			if line: GLib.idle_add(self.update_log, line)

		# Check return code
		self.proc.wait()
		if self.proc.returncode != 0:
			GLib.idle_add(self.progressbar.set_fraction, 1.0)
			GLib.idle_add(self.label.set_text, "Error.")
			return

		GLib.idle_add(self.progressbar.set_fraction, 1.0)
		GLib.idle_add(self.label.set_text, "Done.")

		GLib.idle_add(self.disconnect, self.sigid_destroy)
		GLib.idle_add(self.open_main_window)
		GLib.idle_add(self.destroy)

	def on_destroy(self, button):
		if hasattr(self, 'proc') and self.proc and self.proc.poll() is None:
			self.proc.terminate()
		Gtk.main_quit()

	def open_main_window(self):
		MainWindow()

if __name__ == "__main__":
	UpdaterWindow()
	Gtk.main()
