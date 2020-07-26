import datetime
import dateutil.tz
import os
import subprocess
import threading
import time

from calibre_plugins.caps.config import prefs
from elasticsearch import Elasticsearch, NotFoundError
from PyQt5 import Qt
from PyQt5.QtCore import Qt as QtCore, pyqtSlot, pyqtSignal, QObject

TITLE = 'Power Search'
SUPPORTED_FORMATS = ['CHM', 'CBZ', 'FB2', 'PDB', 'DJVU', 'EPUB', 'MOBI', 'DOCX', 'PDF', 'TXT', 'RTF', 'DJV']

FNULL = open(os.devnull, 'w')

if False:
    get_resources = lambda x: x

def is_exe(fpath):
    return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

def which(program):
    fpath = os.path.split(program)[0]
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None

def concat(book_id, format):
    return '{}:{}'.format(book_id, format)

class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)

class AsyncWorker(Qt.QRunnable):

    def __init__(self, fn, *args, **kwargs):
        super(AsyncWorker, self).__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        self.fn(*self.args, **self.kwargs)
        self.signals.finished.emit()

class SearchDialog(Qt.QDialog):

    def __init__(self, plugin, gui, icon):

        Qt.QDialog.__init__(self, gui)
        self.plugin = plugin
        self.gui = gui
        self.full_db = gui.current_db
        self.db = gui.current_db.new_api

        self.setWindowTitle(TITLE)
        self.setWindowIcon(icon)
        self.setWindowFlags(QtCore.Window | QtCore.WindowTitleHint | QtCore.CustomizeWindowHint)

        self.layout = Qt.QVBoxLayout()
        self.setLayout(self.layout)

        self.layout.addSpacing(20)

        self.search_label = Qt.QLabel('Enter text to search in content')
        self.layout.addWidget(self.search_label)

        self.search_textbox = Qt.QLineEdit(self)
        self.search_textbox.setMinimumWidth(400)
        self.search_textbox.textChanged.connect(self.on_search_text_changed)
        self.layout.addWidget(self.search_textbox)
        self.search_label.setBuddy(self.search_textbox)

        self.search_button = Qt.QPushButton('&Search', self)
        self.search_button.setEnabled(False)
        self.search_button.clicked.connect(self.on_search)
        self.layout.addWidget(self.search_button)

        self.cancel_button = Qt.QPushButton('&Cancel', self)
        self.cancel_button.clicked.connect(self.on_cancel)
        self.cancel_button.setVisible(False)
        self.layout.addWidget(self.cancel_button)

        self.progress_bar = Qt.QProgressBar(self)
        self.progress_bar.setVisible(False)
        policy = self.progress_bar.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.progress_bar.setSizePolicy(policy)
        self.layout.addWidget(self.progress_bar)

        self.layout.addSpacing(20)

        self.conf_button = Qt.QPushButton('&Options...', self)
        self.conf_button.clicked.connect(self.on_config)
        self.layout.addWidget(self.conf_button)

        self.readme_button = Qt.QPushButton('&Readme...', self)
        self.readme_button.clicked.connect(self.on_readme)
        self.layout.addWidget(self.readme_button)

        self.close_button = Qt.QPushButton('&Close', self)
        self.close_button.clicked.connect(self.close)
        self.layout.addWidget(self.close_button)

        self.resize(self.sizeHint())

        self.thread_pool = Qt.QThreadPool()

        self.add_workers_submitted = 0
        self.add_workers_complete = 0

        self.delete_workers_submitted = 0
        self.delete_workers_complete = 0

        self.index_state = {}

    def on_search(self):

        self._set_searching_mode()

        self.canceled = threading.Event()

        self.elastic_search_client = Elasticsearch([prefs['elasticsearch_url']], timeout=20.0)

        if not self.elastic_search_client.ping():
            from calibre.gui2 import error_dialog
            error_dialog(
                self,
                TITLE,
                'Could not connect to ElasticSearch cluster. Please make sure that it\'s running.',
                show=True)
            self._set_idle_mode()
            return

        self.index_state = prefs.get(self.db.library_id, {}).get('index_state', {})

        all_formats = set()
        self.update_list = []
        self.delete_list = []

        epoch = datetime.datetime(1, 1, 1, 0, 0, tzinfo=dateutil.tz.tzutc())

        pdftotext_full_path = None

        pdftotext = prefs['pdftotext_path']

        if is_exe(pdftotext):
            pdftotext_full_path = pdftotext
        elif os.path.sep not in pdftotext:
            pdftotext_full_path = which(pdftotext)

        for book_id in self.db.all_book_ids():
            for format in self.db.formats(book_id):
                if format in SUPPORTED_FORMATS:
                    last_modified = self.db.format_metadata(book_id, format)['mtime']
                    key = concat(book_id, format)
                    all_formats.add(key)
                    if self.index_state.get(key, epoch) < last_modified:
                        self.update_list.append({
                            'book_id': book_id,
                            'format': format,
                            'metadata': str(self.db.get_metadata(book_id)),
                            'input': self.db.format_abspath(book_id, format),
                            'output': self.plugin.temporary_file(suffix='.txt').name,
                            'last_modified': last_modified,
                            'pdftotext': pdftotext_full_path
                        })

        self.delete_list = [k for k in self.index_state.keys() if k not in all_formats]


        if len(self.update_list) + len(self.delete_list) > 0:
            self.thread_pool.setMaxThreadCount(prefs['concurrency'])
            self.add_workers_submitted = len(self.update_list)
            self.add_workers_complete = 0
            self.delete_workers_submitted = len(self.delete_list)
            self.delete_workers_complete = 0
            self.progress_bar.setMaximum(len(self.update_list) + len(self.delete_list) / 20)
            for curr in self.update_list:
                worker = AsyncWorker(self.add_book, curr)
                worker.signals.finished.connect(self.add_worker_complete)
                self.thread_pool.start(worker)
            for curr in self.delete_list:
                worker = AsyncWorker(self.delete_book, curr)
                worker.signals.finished.connect(self.delete_worker_complete)
                self.thread_pool.start(worker)
        else:
            self._set_idle_mode()
            self.do_search()


    def add_worker_complete(self):
        if not self.canceled.is_set():
            self.progress_bar.setValue(self.progress_bar.value() + 1)
        self.add_workers_complete += 1
        self._check_work_complete()

    def delete_worker_complete(self):
        if not self.canceled.is_set():
            if self.delete_workers_complete % 20 == 0:
                self.progress_bar.setValue(self.progress_bar.value() + 1)
        self.delete_workers_complete += 1
        self._check_work_complete()

    def _check_work_complete(self):
        if self.add_workers_complete != self.add_workers_submitted or self.delete_workers_complete != self.delete_workers_submitted:
            return

        if self.canceled.is_set():
            self.progress_bar.setValue(0)
        else:
            self.progress_bar.setValue(self.progress_bar.maximum())
            prefs[self.db.library_id] = {'index_state': self.index_state}

        self.workers_submitted = 0
        self.workers_complete = 0

        self._set_idle_mode()
        self.do_search()

    def add_book(self, args):

        try:
            if self.canceled.is_set():
                return
            id = concat(args['book_id'], args['format'])
            # print('Book {} start processing'.format(id))
            if args['format'] == 'PDF' and args['pdftotext']:
                subprocess.call([args['pdftotext'], '-enc', 'UTF-8', args['input'], args['output']], stdout=FNULL, stderr=FNULL)
            else:
                subprocess.call(['ebook-convert', args['input'], args['output']], stdout=FNULL, stderr=FNULL)
            # print('Book {} converted to plaintext'.format(id))

            content = open(args['output']).readlines()
            doc = {
                'metadata': args['metadata'],
                'content': content
            }
            res = self.elastic_search_client.index(index="library", id=id, body=doc)
            # print('Book {} "{}" in index'.format(id, res['result']))

            self.index_state[id] = args['last_modified']

        except Exception as ex:
            print(ex)

    def delete_book(self, id):
        try:
            self.elastic_search_client.delete(index="library", id=id, ignore=[404])
            # print('Deleted {}'.format(id))
            del self.index_state[id]

        except Exception as ex:
            print(ex)


    def do_search(self):

        matched_ids = []

        req = '{{ "_source": false, "query": {{ "match": {{ "content": "{}"}}}}}}'.format(self.search_textbox.text())
        res = self.elastic_search_client.search(index="library", body=req)

        hits_number = res['hits']['total']['value']
        page_size = len(res['hits']['hits'])

        for i in range(hits_number):
            if not res['hits']['hits']:
                req_paged = '{{ "_source": false, "query": {{ "match": {{ "content": "{}"}}}}, "from": {}, "size": {}}}'.format(
                    self.search_textbox.text(),
                    i,
                    page_size)
                res = self.elastic_search_client.search(index="library", body=req_paged)

            curr = res['hits']['hits'].pop(0)
            matched_ids.append(int(curr['_id'].split(':')[0]))

        self.full_db.set_marked_ids(matched_ids)
        self.gui.search.setEditText('marked:true')
        self.gui.search.do_search()

    def _set_idle_mode(self):
        self.search_textbox.setEnabled(True)
        self.conf_button.setEnabled(True)
        self.search_button.setVisible(True)
        self.readme_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        self.cancel_button.setText('&Cancel')
        self.progress_bar.setVisible(False)

    def _set_searching_mode(self):
        self.search_textbox.setEnabled(False)
        self.search_button.setVisible(False)
        self.readme_button.setEnabled(False)
        self.conf_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.progress_bar.setVisible(True)

    def on_cancel(self):
        self.canceled.set()
        self.cancel_button.setText('Cancelling...')
        self.cancel_button.setEnabled(False)

    def on_search_text_changed(self, text):
        self.search_button.setEnabled(text <> '')

    def reject(self):
        if self.close_button.isEnabled():
            Qt.QDialog.reject(self)

    def on_readme(self):
        text = get_resources('README.txt')
        Qt.QMessageBox.about(self, TITLE, '<html><body><pre>{}</pre></body></html>'.format(text.decode('utf-8')))

    def on_config(self):
        self.plugin.do_user_config(parent=self)
