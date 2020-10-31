import datetime
import dateutil.tz
import functools
import json
import os
import platform
import subprocess
import sys
import threading
import time
from timeit import default_timer as timer

from calibre_plugins.caps.config import prefs
from calibre_plugins.caps.elasticsearch import Elasticsearch
from PyQt5 import Qt, QtWidgets
from PyQt5.QtCore import Qt as QtCore, pyqtSlot, pyqtSignal, QObject

TITLE = 'Power Search'

FNULL = open(os.devnull, 'w')

SUBPROCESS_CREATION_FLAGS = {
    'Linux':   0,
    'Darwin':  0,
    'Windows': 0x00000008 # DETACHED_PROCESS
}

if False:
    get_resources = lambda x: x
    get_icons = lambda x: x

def is_exe(fpath):
    return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

def which(program):
    fpath = os.path.split(program)[0]
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ['PATH'].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None

def concat(book_id, format):
    return '{}:{}'.format(book_id, format)

class WorkerSignals(QObject):
    started = pyqtSignal(dict)
    finished = pyqtSignal(dict)
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
        self.signals.started.emit(*self.args, **self.kwargs)
        self.fn(*self.args, **self.kwargs)
        self.signals.finished.emit(*self.args, **self.kwargs)

class ScrollMessageBox(Qt.QMessageBox):
   def __init__(self, items, *args, **kwargs):
      Qt.QMessageBox.__init__(self, *args, **kwargs)
      self.setWindowTitle(TITLE)
      self.setStandardButtons(Qt.QMessageBox.Ok)
      scroll = Qt.QScrollArea(self)
      scroll.setWidgetResizable(True)
      self.content = Qt.QWidget()
      scroll.setWidget(self.content)
      lay = Qt.QVBoxLayout(self.content)
      for item in items:
         lay.addWidget(Qt.QLabel(item, self))
      self.layout().addWidget(scroll, 0, 0, 1, self.layout().columnCount())
      self.setStyleSheet('QScrollArea{min-width:800px; min-height: 500px}')

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

        self.search_label = Qt.QLabel('Enter text to search in content')
        self.layout.addWidget(self.search_label)

        self.search_text_layout = Qt.QHBoxLayout()

        self.search_textbox = Qt.QLineEdit(self)
        self.search_textbox.setMinimumWidth(400)
        self.search_textbox.textChanged.connect(self.on_search_text_changed)
        self.search_label.setBuddy(self.search_textbox)
        self.search_text_layout.addWidget(self.search_textbox)

        self.search_help_button = Qt.QPushButton('?', self)
        fixed_size_policy = self.search_help_button.sizePolicy()
        fixed_size_policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Fixed)
        self.search_help_button.setSizePolicy(fixed_size_policy)
        self.search_help_button.clicked.connect(self.on_search_help)
        self.search_text_layout.addWidget(self.search_help_button)

        self.layout.addLayout(self.search_text_layout)

        self.search_button = Qt.QPushButton('&Search', self)
        self.search_button.setEnabled(False)
        self.search_button.setDefault(True)
        self.search_button.clicked.connect(self.on_search)
        self.layout.addWidget(self.search_button)

        self.cancel_button = Qt.QPushButton('&Cancel', self)
        self.cancel_button.clicked.connect(self.on_cancel)
        self.cancel_button.setVisible(False)
        self.layout.addWidget(self.cancel_button)

        self.status_label = Qt.QLabel()
        self.status_label.setAlignment(QtCore.AlignCenter)
        self.layout.addWidget(self.status_label)

        self.progress_bar = Qt.QProgressBar(self)
        self.progress_bar.setVisible(False)
        retain_size_policy = self.progress_bar.sizePolicy()
        retain_size_policy.setRetainSizeWhenHidden(True)
        self.progress_bar.setSizePolicy(retain_size_policy)
        self.layout.addWidget(self.progress_bar)

        self.details_button = Qt.QPushButton('&Details', self)
        self.details_button.setVisible(False)
        retain_size_policy = self.details_button.sizePolicy()
        retain_size_policy.setRetainSizeWhenHidden(True)
        self.details_button.setSizePolicy(retain_size_policy)
        self.details_button.setFlat(True)
        self.details_button.setStyleSheet('text-align: left')
        icon = get_icons('images/right-arrow.png')
        self.details_button.setIcon(icon)
        self.details_button.clicked.connect(self.on_details)
        self.layout.addWidget(self.details_button)

        self.details = Qt.QListWidget(self)
        self.details.setVisible(False)
        self.layout.addWidget(self.details)

        self.layout.addStretch()

        self.reindex_layout = Qt.QHBoxLayout()

        self.reindex_button = Qt.QPushButton('&Reindex new books', self)
        self.reindex_button.clicked.connect(self.on_reindex)
        self.reindex_layout.addWidget(self.reindex_button)

        self.reindex_all_button = Qt.QPushButton('&Reindex all books', self)
        self.reindex_all_button.clicked.connect(self.on_reindex_all)
        self.reindex_layout.addWidget(self.reindex_all_button)

        self.layout.addLayout(self.reindex_layout)

        self.conf_button = Qt.QPushButton('&Options...', self)
        self.conf_button.clicked.connect(self.on_config)
        self.layout.addWidget(self.conf_button)

        self.readme_button = Qt.QPushButton('&Readme...', self)
        self.readme_button.clicked.connect(self.on_readme)
        self.layout.addWidget(self.readme_button)

        self.close_button = Qt.QPushButton('&Close', self)
        self.close_button.clicked.connect(self.close)
        self.layout.addWidget(self.close_button)

        self.thread_pool = Qt.QThreadPool()

        self.add_workers_submitted = 0
        self.add_workers_complete = 0

        self.delete_workers_submitted = 0
        self.delete_workers_complete = 0

    def _get_pdftotext_full_path(self):
        pdftotext_full_path = None

        pdftotext = prefs['pdftotext_path']

        if is_exe(pdftotext):
            pdftotext_full_path = pdftotext
        elif os.path.sep not in pdftotext:
            pdftotext_full_path = which(pdftotext)

        return pdftotext_full_path

    def on_search(self):
        self.status_label.setText('')
        self._reindex(self.do_search)

    def _reindex(self, completion_proc=None):
        # Start conversion time dictionaries
        self.timer_start = {}
        self.timer_end = {}
        self.conversion_time_dict = {}

        # Set timer for the whole indexing
        self.timer_total_start = timer()

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

        pdftotext_full_path = self._get_pdftotext_full_path()

        file_formats = prefs['file_formats'].split(',')
        for book_id in self.db.all_book_ids():
            for format in self.db.formats(book_id):
                if format in file_formats:
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
                            'pdftotext': pdftotext_full_path,
                            'completion_proc': completion_proc
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
                worker.signals.started.connect(self.add_worker_started)
                worker.signals.finished.connect(self.add_worker_complete)
                self.thread_pool.start(worker)
            for curr in self.delete_list:
                curr = {'book_id': curr, 'completion_proc': completion_proc}
                worker = AsyncWorker(self.delete_book, curr)
                worker.signals.finished.connect(self.delete_worker_complete)
                self.thread_pool.start(worker)
        else:
            self._set_idle_mode()
            if completion_proc:
                completion_proc()

    def add_worker_started(self, args):
        id = concat(args['book_id'], args['format'])
        item = Qt.QListWidgetItem('Converting {}'.format(args['input']))
        item.setData(QtCore.UserRole, id)
        self.details.addItem(item)
        # Sets the initial timer for conversion
        self.timer_start.update({id: timer()})

    def add_worker_complete(self, args):
        id = concat(args['book_id'], args['format'])
        for i in range(self.details.count()):
            item = self.details.item(i)
            curr_id = item.data(QtCore.UserRole)
            if curr_id == id:
                self.details.takeItem(i)
                # Get the conversion time for this book
                self.timer_end.update({id: timer()})
                self.conversion_time_seconds = self.timer_end[id] - self.timer_start[id]
                self.conversion_time = datetime.timedelta(seconds=self.conversion_time_seconds)
                print('Book {} converted in {}.'.format(id, self.conversion_time))
                # Add it to a dictionary with all the converted books
                self.conversion_time_dict.update({id: self.conversion_time_seconds})
                break
        if not self.canceled.is_set():
            self.progress_bar.setValue(self.progress_bar.value() + 1)
        self.add_workers_complete += 1
        self._check_work_complete(args['completion_proc'])

    def delete_worker_complete(self, args):
        if not self.canceled.is_set():
            if self.delete_workers_complete % 20 == 0:
                self.progress_bar.setValue(self.progress_bar.value() + 1)
        self.delete_workers_complete += 1
        self._check_work_complete(args['completion_proc'])

    def _check_work_complete(self, completion_proc):
        if self.add_workers_complete != self.add_workers_submitted or self.delete_workers_complete != self.delete_workers_submitted:
            return

        if self.canceled.is_set():
            self.status_label.setText('Cancelled')
            self.progress_bar.setValue(0)
        else:
            self.progress_bar.setValue(self.progress_bar.maximum())

        prefs[self.db.library_id] = {'index_state': self.index_state}

        self.workers_submitted = 0
        self.workers_complete = 0

        self._set_idle_mode()
        if completion_proc:
            completion_proc()

    def add_book(self, args):

        try:
            if self.canceled.is_set():
                return
            id = concat(args['book_id'], args['format'])
            os = platform.system()
            # print('Book {} start processing'.format(id))
            creationflags = SUBPROCESS_CREATION_FLAGS[os]
            if args['format'] == 'PDF' and args['pdftotext']:
                subprocess.call([args['pdftotext'], '-enc', 'UTF-8', args['input'], args['output']], stdout=FNULL, stderr=FNULL, creationflags=creationflags)
                print('Book {} converted with pdfttotext.'.format(id))
            else:
                ebook_convert_path = '/Applications/calibre.app/Contents/MacOS/ebook-convert' if os == 'Darwin' else 'ebook-convert'
                subprocess.call([ebook_convert_path, args['input'], args['output']], stdout=FNULL, stderr=FNULL, creationflags=creationflags)
            # print('Book {} converted to plaintext'.format(id))

            if sys.version_info[0] >= 3:
                content = open(args['output'], errors='ignore').readlines()
            else:
                content = open(args['output']).readlines()
            doc = {
                'metadata': args['metadata'],
                'content': content
            }
            res = self.elastic_search_client.index(index='library', id=id, body=doc)
            # print('Book {} "{}" in index'.format(id, res['result']))

            self.index_state[id] = args['last_modified']

        except Exception as ex:
            print(ex)

    def delete_book(self, id):
        try:
            self.elastic_search_client.delete(index='library', id=id['book_id'], ignore=[404])
            # print('Deleted {}'.format(id['book_id']))
            del self.index_state[id['book_id']]

        except Exception as ex:
            print(ex)

    def do_search(self):

        matched_ids = []

        req = {
            '_source': False,
            'query': {
                'simple_query_string': {
                    'query': self.search_textbox.text(),
                    'default_operator': 'AND'
                }
            }
        }

        res = self.elastic_search_client.search(index='library', body=json.dumps(req))

        hits_number = res['hits']['total']['value']
        page_size = len(res['hits']['hits'])

        for i in range(hits_number):
            if not res['hits']['hits']:
                req['from'] = i
                req['size'] = page_size
                res = self.elastic_search_client.search(index='library', body=json.dumps(req))

            curr = res['hits']['hits'].pop(0)
            matched_ids.append(int(curr['_id'].split(':')[0]))

        self.status_label.setText('Found {} books'.format(hits_number))
        self.full_db.set_marked_ids(matched_ids)
        self.gui.search.setEditText('marked:true')
        self.gui.search.do_search()

        # If new books are found, it shows which file took the longest and also the total time of conversion/indexing
        if self.conversion_time_dict:
            self.max_conversion_time_seconds = self.conversion_time_dict[
                max(self.conversion_time_dict, key=self.conversion_time_dict.get)]
            self.max_conversion_time = datetime.timedelta(seconds=self.max_conversion_time_seconds)
            print('Book {} took the longest time to convert: {}'.format(
                max(self.conversion_time_dict, key=self.conversion_time_dict.get), self.max_conversion_time))
            self.timer_total_end = timer()
            self.timer_total = datetime.timedelta(seconds=(self.timer_total_end - self.timer_total_start))
            print('Total time for conversion/indexing: {}'.format(self.timer_total))

    def _set_idle_mode(self):
        self.search_textbox.setEnabled(True)
        self.search_help_button.setEnabled(True)
        self.reindex_button.setEnabled(True)
        self.reindex_all_button.setEnabled(True)
        self.conf_button.setEnabled(True)
        self.search_button.setVisible(True)
        self.readme_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        self.cancel_button.setText('&Cancel')
        self.progress_bar.setVisible(False)
        self.details_button.setVisible(False)
        self.details.setVisible(False)
        self.search_textbox.setFocus(QtCore.OtherFocusReason)

    def _set_searching_mode(self):
        self.search_textbox.setEnabled(False)
        self.search_help_button.setEnabled(False)
        self.reindex_button.setEnabled(False)
        self.reindex_all_button.setEnabled(False)
        self.search_button.setVisible(False)
        self.readme_button.setEnabled(False)
        self.conf_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.progress_bar.setVisible(True)
        self.details_button.setVisible(True)
        icon = get_icons('images/right-arrow.png')
        self.details_button.setIcon(icon)

    def on_details(self):
        self.details.setVisible(not self.details.isVisible())
        icon = get_icons('images/down-arrow.png' if self.details.isVisible() else 'images/right-arrow.png')
        self.details_button.setIcon(icon)

    def on_cancel(self):
        self.status_label.setText('')
        self.canceled.set()
        self.cancel_button.setText('Cancelling...')
        self.cancel_button.setEnabled(False)

    def on_search_text_changed(self, text):
        self.search_button.setEnabled(text != '')

    def reject(self):
        if self.close_button.isEnabled():
            Qt.QDialog.reject(self)

    def on_readme(self):
        text = get_resources('README.txt')
        text = '<html><body><pre>{}</pre></body></html>'.format(text.decode('utf-8'))
        msgbox = ScrollMessageBox([text])
        msgbox.exec_()

    def on_reindex(self):
        self._reindex()

    def on_reindex_all(self):
        from calibre.gui2 import question_dialog

        if question_dialog(self, TITLE, 'You are about to rebuild all fulltext search index. This process might take a while. Are you sure?', default_yes=False):

            self.elastic_search_client = Elasticsearch([prefs['elasticsearch_url']], timeout=20.0)

            if not self.elastic_search_client.ping():
                from calibre.gui2 import error_dialog
                error_dialog(
                    self,
                    TITLE,
                    'Could not connect to ElasticSearch cluster. Please make sure that it\'s running.',
                    show=True)
                return

            self.elastic_search_client.indices.delete(index='library', ignore=[400, 404])

            prefs[self.db.library_id] = {'index_state': {}}

            self._reindex()

    def on_config(self):
        ok_pressed = self.plugin.do_user_config(parent=self)
        if ok_pressed:
            pdftotext_full_path = self._get_pdftotext_full_path()
            if not pdftotext_full_path:
                from calibre.gui2 import error_dialog
                error_dialog(
                    self,
                    TITLE,
                    'Could not find pdftotext tool. Please make sure that the path "{}" is correct.'.format(prefs['pdftotext_path']),
                    show=True)

    def on_search_help(self):
        text = get_resources('USAGE.txt')
        Qt.QMessageBox.about(self, TITLE, '<html><body><pre>{}</pre></body></html>'.format(text.decode('utf-8')))
