import multiprocessing
from string import ascii_lowercase

from PyQt5.Qt import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QCheckBox, Qt
from calibre.utils.config import JSONConfig
from calibre_plugins.caps.elasticsearch_helper import get_elasticsearch_client

TITLE = 'Power Search'

ARCHIVE_FORMATS = ['7Z', 'ZIP', 'RAR']

SUPPORTED_FORMATS = sorted(['AZW3', 'AZW4', 'CBR', 'CBZ', 'CHM', 'DJV', 'DJVU', 'DOC', 'DOCX', 'EPUB', 'FB2', 'KFX', 'MOBI', 'PDB', 'PDF', 'RTF', 'TXT'] + ARCHIVE_FORMATS)

prefs = JSONConfig('plugins/caps')

prefs.defaults['elasticsearch_url'] = 'localhost:9200'
prefs.defaults['elasticsearch_launch_path'] = None
prefs.defaults['pdftotext_path'] = 'pdftotext'
prefs.defaults['concurrency'] = multiprocessing.cpu_count()-1 or 1
prefs.defaults['file_formats'] = ','.join(SUPPORTED_FORMATS)
prefs.defaults['autoindex'] = True


class ConfigWidget(QWidget):

    plugin = None

    def __init__(self, plugin):
        QWidget.__init__(self)

        self.plugin = plugin

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.engine_location_label = QLabel('ElasticSearch engine network path:')
        self.layout.addWidget(self.engine_location_label)

        self.elasticsearch_url_textbox = QLineEdit(self)
        self.elasticsearch_url_textbox.setText(prefs['elasticsearch_url'])
        self.layout.addWidget(self.elasticsearch_url_textbox)
        self.engine_location_label.setBuddy(self.elasticsearch_url_textbox)

        self.layout.addSpacing(10)

        self.engine_launch_path_label = QLabel('ElasticSearch local path:')
        self.layout.addWidget(self.engine_launch_path_label)

        self.elasticsearch_launch_path_textbox = QLineEdit(self)
        self.elasticsearch_launch_path_textbox.setText(prefs['elasticsearch_launch_path'])
        self.layout.addWidget(self.elasticsearch_launch_path_textbox)
        self.engine_launch_path_label.setBuddy(self.elasticsearch_launch_path_textbox)

        self.layout.addSpacing(10)

        self.pdftotext_path_label = QLabel('Path to pdftotext tool:')
        self.layout.addWidget(self.pdftotext_path_label)

        self.pdftotext_path_textbox = QLineEdit(self)
        self.pdftotext_path_textbox.setText(prefs['pdftotext_path'])
        self.layout.addWidget(self.pdftotext_path_textbox)
        self.pdftotext_path_label.setBuddy(self.pdftotext_path_textbox)

        self.layout.addSpacing(10)

        self.concurrency_label = QLabel('Number of parallel processes for text extraction:')
        self.layout.addWidget(self.concurrency_label)

        self.concurrency_textbox = QLineEdit(self)
        self.concurrency_textbox.setText(str(prefs['concurrency']))
        self.layout.addWidget(self.concurrency_textbox)
        self.concurrency_label.setBuddy(self.concurrency_textbox)

        self.layout.addSpacing(10)

        self.formats_label = QLabel('Index book formats:')
        self.layout.addWidget(self.formats_label)

        file_formats = prefs['file_formats'].split(',')

        self.formats_list = QListWidget(self)
        for fmt in SUPPORTED_FORMATS:
            item = QListWidgetItem(fmt)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if fmt in file_formats else Qt.CheckState.Unchecked)
            self.formats_list.addItem(item)
        self.layout.addWidget(self.formats_list)
        self.formats_label.setBuddy(self.formats_list)

        self.layout.addSpacing(10)

        self.autoindex_checkbox = QCheckBox("Automatically index new books on search", self)
        self.autoindex_checkbox.setCheckState(Qt.CheckState.Checked if prefs['autoindex'] else Qt.CheckState.Unchecked)
        self.layout.addWidget(self.autoindex_checkbox)

        self.layout.addSpacing(10)

        self.privacy_label = QLabel('Privacy:')
        self.layout.addWidget(self.privacy_label)

        self.clear_search_history_button = QPushButton('Clear search &history', self)
        self.clear_search_history_button.clicked.connect(self.on_clear_history)
        self.layout.addWidget(self.clear_search_history_button)

        self.clear_search_index_buttin = QPushButton('Clear search &index', self)
        self.clear_search_index_buttin.clicked.connect(self.on_clear_index)
        self.layout.addWidget(self.clear_search_index_buttin)

    def save_settings(self):
        prefs['elasticsearch_url'] = self.elasticsearch_url_textbox.text()
        prefs['elasticsearch_launch_path'] = self.elasticsearch_launch_path_textbox.text()
        prefs['pdftotext_path'] = self.pdftotext_path_textbox.text()
        try:
            prefs['concurrency'] = int(self.concurrency_textbox.text())
        except Exception:
            pass
        file_formats = []
        for i in range(len(SUPPORTED_FORMATS)):
            if self.formats_list.item(i).checkState() == Qt.CheckState.Checked:
                file_formats.append(self.formats_list.item(i).text())
        prefs['file_formats'] = ','.join(file_formats)
        prefs['autoindex'] = True if self.autoindex_checkbox.checkState() == Qt.CheckState.Checked else False

    def on_clear_history(self):
        from calibre.gui2 import info_dialog

        if 'search_lru' in prefs:
            del prefs['search_lru']

        if self.plugin.search_dialog:
            self.plugin.search_dialog.clear_lru()

        info_dialog(
            self,
            TITLE,
            'History cleared',
            show=True)

    def on_clear_index(self):
        from calibre.gui2 import question_dialog, error_dialog

        if question_dialog(
            self,
            TITLE,
            'You are about to clear all fulltext search index. Rebuilding it might take a while. Are you sure?',
            default_yes=False):

            elastic_search_client, reason = get_elasticsearch_client(self, TITLE, prefs['elasticsearch_url'], prefs['elasticsearch_launch_path'])

            if not elastic_search_client:

                error_dialog(
                    self,
                    TITLE,
                    reason,
                    show=True)
                return

            if not elastic_search_client.ping():

                error_dialog(
                    self,
                    TITLE,
                    'Could not connect to ElasticSearch cluster. Please make sure that it\'s running.',
                    show=True)
                return

            elastic_search_client.indices.delete(index='library', ignore=[400, 404])

            prefs[self.plugin.gui.current_db.new_api.library_id] = {'index_state': {}}
