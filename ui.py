from calibre.gui2.actions import InterfaceAction
from calibre_plugins.caps.main import SearchDialog

if False:
    get_icons = lambda x: x

class CapsPlugin(InterfaceAction):

    name = 'Calibre Power Search Plugin'

    action_spec = ('Power Search', None,
            'Run the Power Search', 'Ctrl+Shift+S')

    def genesis(self):
        icon = get_icons('images/icon.png')
        self.qaction.setIcon(icon)
        self.qaction.triggered.connect(self.show_dialog)

    def show_dialog(self):
        base_plugin_object = self.interface_action_base_plugin
        do_user_config = base_plugin_object.do_user_config
        dlg = SearchDialog(base_plugin_object, self.gui, self.qaction.icon())
        dlg.show()

    def apply_settings(self):
        from calibre_plugins.caps.config import prefs
        # In an actual non trivial plugin, you would probably need to
        # do something based on the settings in prefs
        prefs

