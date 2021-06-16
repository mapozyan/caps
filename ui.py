from functools import partial

from calibre.gui2 import error_dialog
from calibre.gui2.actions import InterfaceAction
from calibre_plugins.caps.main import SearchDialog

if False:
    get_icons = lambda x: x

class CapsPlugin(InterfaceAction):

    name = 'Calibre Power Search Plugin'

    action_spec = ('Power Search', None,
            'Run the Power Search', 'Ctrl+Shift+S')

    action_add_menu = True
    action_menu_clone_qaction = True

    search_dialog = None

    def genesis(self):
        icon = get_icons('images/icon.png')
        self.qaction.setIcon(icon)
        self.qaction.triggered.connect(self.show_dialog)
        self.menu = self.qaction.menu()
        cm = partial(self.create_menu_action, self.menu)
        cm('reindex new', 'Reindex new books', triggered=self.reindex_new_books)
        cm('reindex all', 'Reindex all books', triggered=self.reindex_all_books)
        cm('options', 'Options', triggered=self.show_options)
        cm('readme', 'Readme', triggered=self.show_readme)

    def _init_dialog(self):
        base_plugin_object = self.interface_action_base_plugin
        do_user_config = base_plugin_object.do_user_config
        if not self.search_dialog:
            self.search_dialog = SearchDialog(base_plugin_object, self.gui, self.qaction.icon())

    def show_dialog(self):
        self._init_dialog()
        self.search_dialog.show()
        self.search_dialog.raise_()
        self.search_dialog.activateWindow()

    def reindex_new_books(self):
        self._init_dialog()
        self.search_dialog.on_reindex()

    def reindex_all_books(self):
        self._init_dialog()
        self.search_dialog.on_reindex_all()

    def show_options(self):
        self._init_dialog()
        self.search_dialog.on_config()

    def show_readme(self):
        self._init_dialog()
        self.search_dialog.on_readme()

    def apply_settings(self):
        from calibre_plugins.caps.config import prefs
        # In an actual non trivial plugin, you would probably need to
        # do something based on the settings in prefs
        prefs

