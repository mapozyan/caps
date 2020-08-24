from calibre.customize import InterfaceActionBase

class CapsPluginDemo(InterfaceActionBase):

    name                = 'Calibre Power Search Plugin'
    description         = 'Enables Full-text Search'
    supported_platforms = ['linux', 'windows'] # TODO: add support for 'osx'
    author              = 'Michael Apozyan'
    version             = (1, 4, 0)
    minimum_calibre_version = (0, 7, 53)

    actual_plugin       = 'calibre_plugins.caps.ui:CapsPlugin'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.caps.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
        ac = self.actual_plugin_
        if ac is not None:
            ac.apply_settings()


